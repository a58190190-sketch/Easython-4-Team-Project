(() => {
  if (window.__easythonGuideActive) return;
  window.__easythonGuideActive = true;
  const ROOT_ID = "easython-guide-overlay";
  const GUIDE_RED = "#FF0000";
  const SEMANTIC_SELECTOR = 'button,a[href],input:not([type="hidden"]),select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[role="checkbox"],[role="radio"],[tabindex]:not([tabindex="-1"]),[contenteditable="true"],[onclick]';
  const QUIET_MS = 700;        // DOM must be still this long before a step capture
  const MIN_WAIT_MS = 500;     // ...and at least this long after the trigger
  const MAX_WAIT_MS = 3500;    // capture anyway after this (pages that never settle)

  let lastGuideKey = "";
  let latestData = null;
  let redrawTimer = null;
  let lastNavigationRequestKey = "";
  let lastSessionState = null;
  let pollTimer = null;
  let lastMutationAt = Date.now();
  let stepTimer = null;
  let stepReason = "";
  let stepStartedAt = 0;
  let stepInFlight = false;
  let captureSeq = 0;
  // Elements the current guide points at; interacting with them triggers the next step.
  let currentTargets = [];

  // ---------- page helpers ----------
  function pageKeyNow() {
    // Must match flow.page_key_for(): origin + path (+ "#/route" for hash-routed apps).
    return `${location.origin}${location.pathname}${location.hash.startsWith("#/") ? location.hash : ""}`;
  }

  function clearOverlay() {
    document.getElementById(ROOT_ID)?.remove();
    lastGuideKey = "";
    currentTargets = [];
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

  function isRendered(element) {
    if (!element?.isConnected) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  }

  function inViewport(rect) {
    return rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  }

  function isVisible(element) {
    return isRendered(element) && inViewport(element.getBoundingClientRect());
  }

  function matchesStableSignature(element, target) {
    return ["aria_label", "title", "placeholder", "name"].some(key => {
      if (!target[key]) return false;
      const attribute = key === "aria_label" ? "aria-label" : key;
      return element.getAttribute(attribute) === target[key];
    });
  }

  // Find the element a guide/option points at. `anywhere` also accepts elements
  // that are rendered but scrolled out of view (for the scroll arrow).
  function resolveTarget(target, anywhere = false) {
    if (!target?.target_id && !target?.label) return null;
    const usable = anywhere ? isRendered : isVisible;
    const expectedLabel = String(target.label || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
    if (target.info_region) {
      const infoTarget = document.querySelector('[data-easython-info-id="' + CSS.escape(String(target.target_id || "")) + '"]');
      if (infoTarget && usable(infoTarget)) return infoTarget;
    }
    const tagged = document.querySelector('[data-easython-id="' + CSS.escape(String(target.target_id || "")) + '"]');
    if (tagged && elementLabel(tagged) === expectedLabel && usable(tagged)) return tagged;
    const customPointerSelector = target.click_detection === "pointer_cursor_heuristic" && /^[a-z]+$/.test(String(target.tag || ""))
      ? "," + String(target.tag) : "";
    const candidates = [];
    for (const node of document.querySelectorAll(SEMANTIC_SELECTOR + ",a" + customPointerSelector)) {
      if (!usable(node) || (elementLabel(node) !== expectedLabel && !matchesStableSignature(node, target))) continue;
      if (target.tag && node.tagName.toLowerCase() !== target.tag) continue;
      if (target.role && node.getAttribute("role") !== target.role) continue;
      if (target.type && node.getAttribute("type") !== target.type) continue;
      candidates.push(node);
    }
    const signatureMatches = candidates.filter(node => matchesStableSignature(node, target));
    if (signatureMatches.length === 1) return signatureMatches[0];
    const exactMatches = candidates.filter(node => elementLabel(node) === expectedLabel);
    if (exactMatches.length === 1) return exactMatches[0];
    if (exactMatches.length > 1) {
      const ranked = exactMatches.map(node => {
        const rect = node.getBoundingClientRect();
        return { node, distance: Math.abs(rect.left - Number(target.x || 0)) + Math.abs(rect.top - Number(target.y || 0)) };
      }).sort((left, right) => left.distance - right.distance);
      if (ranked[0].distance <= 50 && (!ranked[1] || ranked[1].distance - ranked[0].distance >= 30)) return ranked[0].node;
    }
    return null;
  }

  // ---------- step capture (sent only on triggers, never on a timer) ----------
  function viewportInfo() {
    const root = document.documentElement;
    return {
      width: innerWidth, height: innerHeight,
      document_width: Math.max(root.scrollWidth, document.body?.scrollWidth || 0),
      document_height: Math.max(root.scrollHeight, document.body?.scrollHeight || 0),
      scroll_x: Math.round(scrollX), scroll_y: Math.round(scrollY), device_pixel_ratio: devicePixelRatio
    };
  }

  function actionTypeOf(element) {
    return element.matches('input[type="search"],[role="searchbox"]') ? "search_input"
      : element.matches('input[type="text"],input[type="email"],input[type="tel"],input[type="password"],input[type="number"],input:not([type]),textarea,[contenteditable="true"]') ? "text_input"
      : element.matches('input[type="checkbox"],input[type="radio"],[role="checkbox"],[role="radio"]') ? "toggle"
      : element.matches("select") ? "select"
      : element.matches('a,[role="link"]') ? "link"
      : element.matches('button,[role="button"],input[type="submit"],input[type="button"]') ? "button"
      : element.matches('[role="menuitem"],[role="tab"],[role="option"]') ? "menu_item" : "control";
  }

  function hitReachable(element, rect) {
    const x = (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2;
    const y = (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2;
    return document.elementsFromPoint(x, y).some(hit => hit === element || element.contains(hit) || hit.contains(element));
  }

  // Controls on the page, visible ones first, then off-screen ones so the AI can
  // point below the fold. Each gets a data-easython-id the guide can find again.
  // Values typed by the user are never read.
  function collectElements() {
    captureSeq += 1;
    document.querySelectorAll('[data-easython-id^="s"]').forEach(node => node.removeAttribute("data-easython-id"));
    const seen = new Set();
    const nodes = [];
    for (const element of document.querySelectorAll(SEMANTIC_SELECTOR)) {
      if (nodes.length >= 400) break;
      if (!isRendered(element)) continue;
      seen.add(element);
      nodes.push(element);
    }
    // Plain DIV/SPAN controls with a pointer cursor (delegated click handlers).
    let inspected = 0;
    let custom = 0;
    for (const element of document.querySelectorAll("body *")) {
      if (++inspected > 2500 || custom >= 60) break;
      if (seen.has(element) || element.closest("#" + ROOT_ID)) continue;
      const rect = element.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8 || !inViewport(rect)) continue;
      if (getComputedStyle(element).cursor !== "pointer") continue;
      const parent = element.parentElement;
      if (parent && (parent.closest(SEMANTIC_SELECTOR) || getComputedStyle(parent).cursor === "pointer")) continue;
      seen.add(element);
      nodes.push(element);
      custom += 1;
    }
    const measured = nodes.map(element => {
      const rect = element.getBoundingClientRect();
      return { element, rect, inView: inViewport(rect), semantic: element.matches(SEMANTIC_SELECTOR) };
    });
    measured.sort((a, b) => (Number(b.inView) - Number(a.inView)) || (a.rect.top - b.rect.top));
    return measured.slice(0, 220).map(({ element, rect, inView, semantic }, index) => {
      const id = `s${captureSeq}_${index}`;
      element.setAttribute("data-easython-id", id);
      const style = getComputedStyle(element);
      const disabled = Boolean(element.matches(":disabled") || element.closest('[aria-disabled="true"]'));
      const searchText = [element.type, element.name, element.id, element.getAttribute("aria-label"), element.getAttribute("placeholder"), element.closest("form")?.getAttribute("role")].filter(Boolean).join(" ");
      return {
        id, dom_id: element.id || "",
        tag: element.tagName.toLowerCase(), role: element.getAttribute("role") || "", label: rawElementLabel(element),
        aria_label: element.getAttribute("aria-label") || "", title: element.getAttribute("title") || "",
        placeholder: element.getAttribute("placeholder") || "", name: element.getAttribute("name") || "",
        href: element instanceof HTMLAnchorElement ? (element.host !== location.host ? element.host + element.pathname : element.pathname) : "",
        type: element.getAttribute("type") || "", action_type: actionTypeOf(element),
        is_search: element.matches('input,[role="searchbox"],textarea') && /search|검색/i.test(searchText),
        click_detection: semantic ? "semantic" : "pointer_cursor_heuristic",
        actionable: !disabled && style.pointerEvents !== "none" && (!inView || hitReachable(element, rect)),
        hover_actionable: false, hover_reveals: [], disabled, in_view: inView, stable: true,
        x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height)
      };
    });
  }

  async function sendStep(reason) {
    if (stepInFlight) return { sent: false };
    stepInFlight = true;
    const href = location.href;
    try {
      const result = await chrome.runtime.sendMessage({
        type: "EASYTHON_STEP_CAPTURE", reason, url: href, title: document.title,
        viewport: viewportInfo(), elements: collectElements()
      });
      if (result?.sent) lastNavigationRequestKey = href;
      return result;
    } catch (_) {
      return { sent: false };
    } finally {
      stepInFlight = false;
    }
  }

  // Debounce: wait until the DOM has been quiet for QUIET_MS (menus finished
  // opening, SPA finished rendering), then capture once.
  function scheduleStepCapture(reason) {
    stepReason = reason;
    stepStartedAt = Date.now();
    lastMutationAt = Date.now();
    clearTimeout(stepTimer);
    const check = () => {
      const now = Date.now();
      const waited = now - stepStartedAt;
      if ((now - lastMutationAt >= QUIET_MS && waited >= MIN_WAIT_MS) || waited >= MAX_WAIT_MS) {
        stepTimer = null;
        sendStep(stepReason);
      } else {
        stepTimer = setTimeout(check, 150);
      }
    };
    stepTimer = setTimeout(check, 300);
  }

  function isGuidedElement(node) {
    return node instanceof Node && currentTargets.some(target => target === node || target.contains(node));
  }

  // Trigger ①: the user clicked the guided element (or one of the ask options).
  document.addEventListener("click", event => {
    if (isGuidedElement(event.target)) scheduleStepCapture("click");
  }, true);
  // Trigger ③: input finished (Enter, a select/checkbox change, or leaving a filled field).
  document.addEventListener("keydown", event => {
    if (event.key === "Enter" && isGuidedElement(event.target)) scheduleStepCapture("input");
  }, true);
  document.addEventListener("change", event => {
    if (isGuidedElement(event.target)) scheduleStepCapture("input");
  }, true);
  document.addEventListener("focusout", event => {
    const field = event.target;
    if (!isGuidedElement(field) || !(field instanceof HTMLElement) || !field.matches('input,textarea,[contenteditable="true"]')) return;
    // Only whether something was typed is checked; the value itself is never sent.
    if ((field.value ?? field.textContent ?? "").length > 0) scheduleStepCapture("input");
  }, true);

  // ---------- overlay ----------
  function sendAction(action, extra = {}) {
    return chrome.runtime.sendMessage({ type: "EASYTHON_GUIDE_ACTION", action, ...extra }).catch(() => ({ ok: false }));
  }

  function makeButton(text, onClick, primary = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    Object.assign(button.style, {
      font: "700 16px/1.3 'Malgun Gothic', Arial, sans-serif", padding: "10px 14px", margin: "8px 8px 0 0",
      borderRadius: "8px", border: primary ? "0" : "2px solid #fff", cursor: "pointer",
      color: primary ? GUIDE_RED : "#fff", background: primary ? "#fff" : "transparent"
    });
    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      onClick();
    });
    return button;
  }

  function makeRing(rect, dashed = false) {
    const ring = document.createElement("div");
    Object.assign(ring.style, {
      position: "fixed", left: `${rect.left - 4}px`, top: `${rect.top - 4}px`,
      width: `${rect.width + 8}px`, height: `${rect.height + 8}px`,
      border: `3px ${dashed ? "dashed" : "solid"} ${GUIDE_RED}`, borderRadius: "8px", boxSizing: "border-box", pointerEvents: "none"
    });
    return ring;
  }

  function scrollDirection(rect) {
    if (rect.top >= innerHeight) return { arrow: "↓", text: "아래로 스크롤해 주세요" };
    if (rect.bottom <= 0) return { arrow: "↑", text: "위로 스크롤해 주세요" };
    if (rect.left >= innerWidth) return { arrow: "→", text: "오른쪽으로 스크롤해 주세요" };
    return { arrow: "←", text: "왼쪽으로 스크롤해 주세요" };
  }

  function retryButton() {
    return makeButton("다시 안내", () => scheduleStepCapture("retry"));
  }

  // Builds the instruction card. One sentence, plus buttons for ask/done/blocked.
  function buildCard(guide, extraLine = "") {
    const card = document.createElement("div");
    Object.assign(card.style, {
      position: "fixed", left: "-10000px", top: "-10000px", maxWidth: Math.max(220, Math.min(460, innerWidth - 24)) + "px",
      padding: "14px 16px", color: "#fff", background: GUIDE_RED, borderRadius: "10px", boxSizing: "border-box",
      font: "700 18px/1.45 'Malgun Gothic', Arial, sans-serif", boxShadow: "0 4px 16px rgba(0,0,0,.3)", pointerEvents: "auto"
    });
    const text = document.createElement("div");
    text.textContent = guide.status === "ask" ? (guide.question || guide.say) : guide.say;
    card.appendChild(text);
    for (const line of [guide.input_hint, guide.warning, extraLine]) {
      if (!line) continue;
      const detail = document.createElement("div");
      detail.textContent = line;
      Object.assign(detail.style, { marginTop: "6px", fontSize: "16px", fontWeight: "600" });
      card.appendChild(detail);
    }
    const buttons = document.createElement("div");
    if (guide.status === "ask") {
      guide.options.forEach((option, index) => {
        buttons.appendChild(makeButton(option.label, () => sendAction("choose", { guide_id: guide.id, option: index }), true));
      });
      buttons.appendChild(makeButton("잘 모르겠어요", () => sendAction("choose", { guide_id: guide.id, option: "unknown" })));
    } else if (guide.status === "done") {
      buttons.appendChild(makeButton("확인", () => sendAction("dismiss"), true));
      buttons.appendChild(makeButton("아직 안 끝났어요", async () => {
        const result = await sendAction("reopen");
        if (result?.ok) scheduleStepCapture("retry");
      }));
    } else {
      // A recommendation that has other choices on screen ("간편인증 추천") can be
      // switched to a question card; this costs no AI call.
      if (guide.status === "next" && (guide.options || []).length >= 2) {
        buttons.appendChild(makeButton("다른 방법 보기", () => sendAction("alternatives", { guide_id: guide.id }), true));
      }
      buttons.appendChild(retryButton());
    }
    card.appendChild(buttons);
    return card;
  }

  function dock(card, rect = null) {
    const cardRect = card.getBoundingClientRect();
    const left = Math.max(8, (innerWidth - cardRect.width) / 2);
    // Dock at the bottom unless the highlighted target sits there.
    const atBottom = !rect || rect.top < innerHeight / 2;
    card.style.left = left + "px";
    card.style.top = (atBottom ? innerHeight - cardRect.height - 12 : 12) + "px";
  }

  function placeNear(card, rect) {
    const cardRect = card.getBoundingClientRect();
    const gap = 12;
    const left = Math.max(8, Math.min(innerWidth - cardRect.width - 8, rect.left));
    if (rect.bottom + gap + cardRect.height <= innerHeight - 8) {
      card.style.left = left + "px";
      card.style.top = rect.bottom + gap + "px";
    } else if (rect.top - gap - cardRect.height >= 8) {
      card.style.left = left + "px";
      card.style.top = rect.top - gap - cardRect.height + "px";
    } else {
      dock(card, rect);
    }
  }

  function waitingGuide() {
    return { id: "waiting", status: "waiting", say: "다음 안내를 준비하고 있어요. 잠시만 기다려 주세요." };
  }

  function drawGuide(guide, transparency = 10) {
    if (!guide) { clearOverlay(); return; }
    let target = null;
    let offscreen = null;
    const optionTargets = [];
    if (guide.status === "next" || guide.status === "user_input") {
      target = resolveTarget(guide);
      if (!target) {
        const anywhere = resolveTarget(guide, true);
        if (anywhere) offscreen = { node: anywhere, ...scrollDirection(anywhere.getBoundingClientRect()) };
      }
    } else if (guide.status === "ask") {
      for (const option of guide.options || []) {
        const node = resolveTarget(option.target);
        if (node) optionTargets.push(node);
      }
    }
    const rect = target?.getBoundingClientRect() || null;
    const rectKey = node => { const r = node.getBoundingClientRect(); return `${Math.round(r.left)}:${Math.round(r.top)}:${Math.round(r.width)}:${Math.round(r.height)}`; };
    const key = [guide.id, transparency, innerWidth, innerHeight, target ? rectKey(target) : "", offscreen?.arrow || "", optionTargets.map(rectKey).join("|")].join(";");
    currentTargets = [target, offscreen?.node, ...optionTargets].filter(Boolean);
    if (lastGuideKey === key) return;
    document.getElementById(ROOT_ID)?.remove();
    lastGuideKey = key;

    const host = document.createElement("div");
    host.id = ROOT_ID;
    Object.assign(host.style, { position: "fixed", inset: "0", zIndex: "2147483647", pointerEvents: "none" });
    applyTransparency(host, transparency);
    const layer = host.attachShadow({ mode: "closed" });
    // Attach before measuring the card; detached fixed elements report zero size.
    document.documentElement.appendChild(host);

    if (rect) layer.appendChild(makeRing(rect));
    for (const node of optionTargets) layer.appendChild(makeRing(node.getBoundingClientRect(), true));

    let extraLine = "";
    if (offscreen) extraLine = `${offscreen.arrow} ${offscreen.text}`;
    else if ((guide.status === "next" || guide.status === "user_input") && !target) extraLine = "안내할 버튼이 화면에 보이지 않아요.";
    const card = guide.status === "waiting" ? (() => {
      const waiting = buildCard({ ...guide, status: "waiting" });
      waiting.lastChild.remove(); // no buttons while waiting
      return waiting;
    })() : buildCard(guide, extraLine);
    layer.appendChild(card);
    if (rect) placeNear(card, rect);
    else dock(card);
  }

  // ---------- polling the local app (through the background worker) ----------
  async function pollGuide() {
    if (!chrome.runtime?.id) {
      // The extension was reloaded or removed; this orphaned script must stop.
      clearInterval(pollTimer);
      observer.disconnect();
      clearOverlay();
      return;
    }
    try {
      const reply = await chrome.runtime.sendMessage({ type: "EASYTHON_GUIDE_POLL" });
      if (!reply?.ok) return;
      const data = reply.data;
      const sessionTab = Boolean(reply.sessionTab);
      const pageKey = pageKeyNow();
      const sessionState = Boolean(data.navigation_active);
      if (lastSessionState !== sessionState) {
        lastSessionState = sessionState;
        chrome.runtime.sendMessage({ type: "EASYTHON_SESSION_STATE", active: sessionState }).catch(() => {});
      }
      // Trigger ②: the session tab is on a page the current guide was not made
      // for (link followed, SPA route change, another site, new tab).
      const guideForOtherPage = data.guide && data.guide.page_key !== pageKey;
      if (sessionTab && sessionState && guideForOtherPage && lastNavigationRequestKey !== location.href && !stepTimer && !stepInFlight) {
        scheduleStepCapture("url");
      }
      let guide = data.guide?.page_key === pageKey ? data.guide : null;
      if (!guide && sessionTab && sessionState) guide = waitingGuide();
      latestData = { guide, transparency: data.transparency ?? 10 };
      const currentOverlay = document.getElementById(ROOT_ID);
      if (currentOverlay) applyTransparency(currentOverlay, latestData.transparency);
      drawGuide(guide, latestData.transparency);
    } catch (_) {
      latestData = null;
      clearOverlay();
    }
  }

  // The background worker asks for a capture when the user returns from a closed tab.
  chrome.runtime.onMessage.addListener(message => {
    if (message?.type === "EASYTHON_FORCE_CAPTURE") scheduleStepCapture(String(message.reason || "return"));
  });

  // Remove a banner injected by an older extension build before drawing.
  clearOverlay();
  const observer = new MutationObserver(records => {
    // Our own overlay being redrawn is not a page change.
    const ownChange = records.every(record => [...record.addedNodes, ...record.removedNodes].every(node => node.id === ROOT_ID) && record.target === document.documentElement);
    if (ownChange) return;
    lastMutationAt = Date.now();
    if (!latestData) return;
    clearTimeout(redrawTimer);
    redrawTimer = setTimeout(() => {
      redrawTimer = null;
      const data = latestData;
      if (!data) { clearOverlay(); return; }
      drawGuide(data.guide ?? null, data.transparency ?? 10);
    }, 90);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });

  window.addEventListener("scroll", () => { lastGuideKey = ""; }, { passive: true });
  window.addEventListener("resize", () => { lastGuideKey = ""; }, { passive: true });
  pollTimer = setInterval(pollGuide, 400);
  pollGuide();
})();
