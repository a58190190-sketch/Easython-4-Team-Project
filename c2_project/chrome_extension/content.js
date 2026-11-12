(() => {
  if (window.__easythonGuideActive) return;
  window.__easythonGuideActive = true;
  const ROOT_ID = "easython-guide-overlay";
  const GUIDE_RED = "#FF0000";
  let lastGuideKey = "";
  let latestData = null;
  let redrawTimer = null;

  function clearOverlay() {
    document.getElementById(ROOT_ID)?.remove();
    lastGuideKey = "";
  }

  function applyTransparency(element, value) {
    const opacity = String(1 - Math.max(0, Math.min(100, Number(value))) / 100);
    element.style.setProperty("opacity", opacity, "important");
  }

  function rawElementLabel(element) {
    return (element.getAttribute("aria-label") || element.getAttribute("title") || element.innerText || element.getAttribute("placeholder") || element.getAttribute("name") || element.tagName)
      .replace(/\s+/g, " ").trim().slice(0, 100);
  }

  function elementLabel(element) {
    return rawElementLabel(element).toLocaleLowerCase();
  }

  function isVisible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  }

  function matchesStableSignature(element, guide) {
    if (guide.stable && guide.dom_id && element.id === guide.dom_id) return true;
    return ["aria_label", "title", "placeholder", "name"].some(key => {
      if (!guide[key]) return false;
      const attribute = key === "aria_label" ? "aria-label" : key;
      return element.getAttribute(attribute) === guide[key];
    });
  }

  function resolveTarget(guide) {
    if (!guide) return null;
    const expectedLabel = String(guide.label || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
    const idTarget = guide.dom_id ? document.getElementById(guide.dom_id) : null;
    if (idTarget && isVisible(idTarget) && (elementLabel(idTarget) === expectedLabel || matchesStableSignature(idTarget, guide))) return idTarget;
    const easythonTarget = document.querySelector(`[data-easython-id="${CSS.escape(String(guide.target_id || ""))}"]`);
    if (easythonTarget && elementLabel(easythonTarget) === expectedLabel && isVisible(easythonTarget)) return easythonTarget;
    const nodes = document.querySelectorAll('button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="searchbox"]');
    const candidates = [];
    for (const node of nodes) {
      if (!isVisible(node) || (elementLabel(node) !== expectedLabel && !matchesStableSignature(node, guide))) continue;
      if (guide.tag && node.tagName.toLowerCase() !== guide.tag) continue;
      if (guide.role && node.getAttribute("role") !== guide.role) continue;
      if (guide.type && node.getAttribute("type") !== guide.type) continue;
      candidates.push(node);
    }
    const signatureMatches = candidates.filter(node => matchesStableSignature(node, guide));
    if (signatureMatches.length === 1) return signatureMatches[0];
    const exactMatches = candidates.filter(node => elementLabel(node) === expectedLabel);
    if (exactMatches.length === 1) return exactMatches[0];
    if (exactMatches.length > 1) {
      const ranked = exactMatches.map(node => {
        const rect = node.getBoundingClientRect();
        return { node, distance: Math.abs(rect.left - Number(guide.x || 0)) + Math.abs(rect.top - Number(guide.y || 0)) };
      }).sort((left, right) => left.distance - right.distance);
      if (ranked[0].distance <= 50 && (!ranked[1] || ranked[1].distance - ranked[0].distance >= 30)) return ranked[0].node;
    }
    return null;
  }

  function drawGuide(guide, display, transparency = 10) {
    const target = resolveTarget(guide);
    const rect = target?.getBoundingClientRect() || null;
    const viewport = display?.viewport || {};
    const root = document.documentElement;
    const documentWidth = Math.max(Number(viewport.document_width || 0), root.scrollWidth, document.body?.scrollWidth || 0);
    const documentHeight = Math.max(Number(viewport.document_height || 0), root.scrollHeight, document.body?.scrollHeight || 0);
    const hints = [];
    const hasVisibleActionableUI = Boolean(guide?.has_visible_actionable_ui || display?.has_visible_actionable_ui);
    const showScrollHints = !target && !hasVisibleActionableUI && Boolean(guide || display);
    if (showScrollHints && documentHeight > innerHeight * 1.03 && scrollY + innerHeight < documentHeight - 2) {
      hints.push({ arrow: "↓", label: "아래쪽 방향으로 스크롤", edge: "bottom" });
    }
    if (showScrollHints && hints.length === 0 && documentWidth > innerWidth * 1.03) {
      if (scrollX + innerWidth < documentWidth - 2) hints.push({ arrow: "→", label: "오른쪽 방향으로 스크롤", edge: "right" });
      else if (scrollX > 0) hints.push({ arrow: "←", label: "왼쪽 방향으로 스크롤", edge: "left" });
    }
    if (showScrollHints && hints.length === 0 && documentHeight > innerHeight * 1.03 && scrollY > 0) {
      hints.push({ arrow: "↑", label: "위쪽 방향으로 스크롤", edge: "top" });
    }
    const key = `${guide?.id || ""}:${transparency}:${target ? elementLabel(target) : ""}:${rect ? `${Math.round(rect.left)}:${Math.round(rect.top)}:${Math.round(rect.width)}:${Math.round(rect.height)}` : ""}:${hints.map(hint => hint.edge).join(",")}`;
    if (!target && !hints.length) { clearOverlay(); return; }
    if (lastGuideKey === key) return;
    clearOverlay();
    lastGuideKey = key;

    const host = document.createElement("div");
    host.id = ROOT_ID;
    Object.assign(host.style, {
      position: "fixed", inset: "0", zIndex: "2147483647", pointerEvents: "none",
      font: "700 14px/1.35 Arial, sans-serif"
    });
    applyTransparency(host, transparency);

    if (target && rect) {
      const ring = document.createElement("div");
      Object.assign(ring.style, {
        position: "fixed", left: `${rect.left - 3}px`, top: `${rect.top - 3}px`,
        width: `${rect.width + 6}px`, height: `${rect.height + 6}px`,
        border: `2px solid ${GUIDE_RED}`, borderRadius: "6px", boxSizing: "border-box",
        background: "transparent", boxShadow: "none"
      });
      host.appendChild(ring);
      if (guide.action_text) {
        const card = document.createElement("div");
        card.textContent = guide.action_card_text || guide.action_text;
        Object.assign(card.style, {
          position: "fixed", left: "-10000px", top: "-10000px", maxWidth: Math.max(120, Math.min(280, innerWidth - 24)) + "px",
          padding: "8px 10px", color: "#fff", background: GUIDE_RED, border: "1px solid #fff",
          borderRadius: "6px", boxSizing: "border-box", whiteSpace: "normal", lineHeight: "1.35",
          font: "600 13px/1.35 Arial, sans-serif", boxShadow: "0 2px 8px rgba(0,0,0,.22)", pointerEvents: "none"
        });
        host.appendChild(card);
        const cardRect = card.getBoundingClientRect();
        const gap = 10;
        const candidates = [
          [rect.left, rect.top - cardRect.height - gap],
          [rect.left, rect.bottom + gap],
          [rect.right + gap, rect.top],
          [rect.left - cardRect.width - gap, rect.top],
          [8, 8], [innerWidth - cardRect.width - 8, 8],
          [8, innerHeight - cardRect.height - 8],
          [innerWidth - cardRect.width - 8, innerHeight - cardRect.height - 8]
        ];
        const guideRect = { left: rect.left - 5, right: rect.right + 5, top: rect.top - 5, bottom: rect.bottom + 5 };
        const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
        const controls = Array.from(document.querySelectorAll('button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"]'))
          .filter(node => node !== target && isVisible(node))
          .map(node => node.getBoundingClientRect());
        const location = candidates.find(([left, top]) => {
          const candidate = { left, top, right: left + cardRect.width, bottom: top + cardRect.height };
          return left >= 8 && top >= 8 && candidate.right <= innerWidth - 8 && candidate.bottom <= innerHeight - 8 &&
            !intersects(candidate, guideRect) && !controls.some(control => intersects(candidate, control));
        });
        if (location) {
          card.style.left = location[0] + "px";
          card.style.top = location[1] + "px";
        } else {
          card.remove();
        }
      }
    }

    for (const hint of hints) {
      const cue = document.createElement("div");
      cue.textContent = `${hint.arrow} ${hint.label}`;
      Object.assign(cue.style, {
        position: "fixed", padding: "10px 14px", color: "#fff", background: GUIDE_RED,
        borderRadius: "9px", boxShadow: "0 2px 9px rgba(0,0,0,.35)", fontSize: "16px", whiteSpace: "nowrap"
      });
      if (hint.edge === "left") Object.assign(cue.style, { left: "8px", top: "50%", transform: "translateY(-50%)" });
      if (hint.edge === "right") Object.assign(cue.style, { right: "8px", top: "50%", transform: "translateY(-50%)" });
      if (hint.edge === "top") Object.assign(cue.style, { top: "8px", left: "50%", transform: "translateX(-50%)" });
      if (hint.edge === "bottom") Object.assign(cue.style, { bottom: "8px", left: "50%", transform: "translateX(-50%)" });
      host.appendChild(cue);
    }
    document.documentElement.appendChild(host);
  }

  async function pollGuide() {
    try {
      const response = await fetch("http://127.0.0.1:8765/guide", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      const pageKey = `${location.origin}${location.pathname}`;
      const guide = data.guide?.page_key === pageKey ? data.guide : null;
      const display = data.display?.page_key === pageKey ? data.display : null;
      latestData = { guide, display, transparency: data.transparency ?? 10 };
      const currentOverlay = document.getElementById(ROOT_ID);
      if (currentOverlay) applyTransparency(currentOverlay, latestData.transparency);
      drawGuide(guide, display, latestData.transparency);
    } catch (_) {
      latestData = null;
      clearOverlay();
    }
  }

  // Remove a banner injected by an older extension build before drawing the outline-only guide.
  clearOverlay();
  const observer = new MutationObserver(() => {
    if (!latestData) return;
    clearTimeout(redrawTimer);
    redrawTimer = setTimeout(() => drawGuide(latestData.guide, latestData.display, latestData.transparency), 90);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });

  window.addEventListener("scroll", () => { lastGuideKey = ""; }, { passive: true });
  window.addEventListener("resize", () => { lastGuideKey = ""; }, { passive: true });
  setInterval(pollGuide, 350);
  pollGuide();
})();
