const msg = document.getElementById("msg");
const button = document.getElementById("send");
const opacity = document.getElementById("opacity");
const opacityValue = document.getElementById("opacityValue");
const BRIDGE_ORIGIN = "http://127.0.0.1/*";
let bridgeGranted = false;
let opacityTimer = null;

async function ensureBridgePermission() {
  if (!bridgeGranted) {
    bridgeGranted = await chrome.permissions.request({ origins: [BRIDGE_ORIGIN] });
  }
  return bridgeGranted;
}

async function loadGuideSettings() {
  try {
    bridgeGranted = await chrome.permissions.contains({ origins: [BRIDGE_ORIGIN] });
    if (!bridgeGranted) {
      msg.textContent = "버튼을 누르면 현재 탭 접근 권한과 로컬 앱 연결 권한을 요청합니다.";
      return;
    }
    fetch("http://127.0.0.1:8765/heartbeat", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
    const response = await fetch("http://127.0.0.1:8765/guide", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    opacity.value = String(data.transparency ?? 10);
    opacityValue.value = opacity.value + "%";
    msg.textContent = "현재 탭에서 동작하며, 새 페이지에는 자동으로 접근하지 않습니다.";
  } catch (_) {
    msg.textContent = "Python 앱을 먼저 실행하세요.";
  }
}

opacity.addEventListener("input", async () => {
  opacityValue.value = opacity.value + "%";
  if (!await ensureBridgePermission()) {
    msg.textContent = "투명도를 적용하려면 로컬 앱 연결 권한이 필요합니다.";
    return;
  }
  clearTimeout(opacityTimer);
  opacityTimer = setTimeout(async () => {
    try {
      const response = await fetch("http://127.0.0.1:8765/guide/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transparency: Number(opacity.value) })
      });
      if (!response.ok) throw new Error();
      msg.textContent = "가이드 투명도 " + opacity.value + "% 적용됨";
    } catch (_) {
      msg.textContent = "Python 앱을 실행한 뒤 다시 조절하세요.";
    }
  }, 60);
});

button.addEventListener("click", async () => {
  button.disabled = true;
  msg.textContent = "현재 화면과 UI 요소를 분석 중…";
  try {
    if (!await ensureBridgePermission()) {
      throw new Error("Easython 로컬 앱 연결 권한이 필요합니다.");
    }
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || "")) {
      throw new Error("일반 http/https 웹페이지에서 실행해 주세요.");
    }

    // activeTab is granted for this page after the user opens this extension popup.
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    const [{ result: page }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: async () => {
        const popularKeywordElements = new Set();
        const popularHeadings = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,strong,b,label,span,p,div"))
          .filter(el => el.children.length === 0 && el.innerText && el.innerText.trim().length <= 30 && /인기\s*(검색어|키워드)|popular\s*(search|keyword)/i.test(el.innerText.trim()));
        for (const heading of popularHeadings) {
          let section = heading.parentElement;
          for (let depth = 0; section && depth < 4; depth += 1, section = section.parentElement) {
            const controls = Array.from(section.querySelectorAll('a,button,[role="option"]'))
              .filter(el => el !== heading && el.innerText?.trim() && el.innerText.trim().length <= 60);
            if (controls.length > 0 && controls.length <= 10 && (section.innerText || "").length <= 220) {
              controls.forEach(el => popularKeywordElements.add(el));
              break;
            }
          }
        }
        const baseCandidates = Array.from(document.querySelectorAll(
          'button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[onclick],[oncontextmenu]'
        ));
        const candidates = Array.from(new Set([...baseCandidates, ...popularKeywordElements]));
        const elements = [];
        for (const el of candidates) {
          const style = getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) continue;
          const disabled = Boolean(el.matches(":disabled") || el.closest('[aria-disabled="true"]'));
          const inView = rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
          const centerX = (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2;
          const centerY = (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2;
          const hitStack = inView ? document.elementsFromPoint(centerX, centerY) : [];
          const semanticAction = el.matches('button,a[href],input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"]') || el.hasAttribute("oncontextmenu");
          const clickReachable = inView && !disabled && style.pointerEvents !== "none" && (semanticAction || typeof el.onclick === "function" || el.hasAttribute("onclick")) &&
            hitStack.some(hit => hit === el || el.contains(hit) || hit.contains(el));
          const actionType = el.matches('input[type="search"],[role="searchbox"]') ? "search_input"
            : el.matches('input[type="text"],input:not([type]),textarea') ? "text_input"
            : el.matches('input[type="checkbox"],input[type="radio"]') ? "toggle"
            : el.matches("select") ? "select"
            : el.matches("a,[role=\"link\"]") ? "link"
            : el.matches("button,[role=\"button\"]") ? "button"
            : el.matches('[role="menuitem"],[role="tab"],[role="option"]') ? "menu_item" : "control";
          const id = `e${elements.length}`;
          el.setAttribute("data-easython-id", id);
          const label = (el.getAttribute("aria-label") || el.getAttribute("title") || el.innerText || el.getAttribute("placeholder") || el.getAttribute("name") || el.tagName).replace(/\s+/g, " ").trim().slice(0, 100);
          elements.push({
            id,
            element: el,
            dom_id: el.id || "",
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute("role") || "",
            label,
            aria_label: el.getAttribute("aria-label") || "",
            title: el.getAttribute("title") || "",
            placeholder: el.getAttribute("placeholder") || "",
            name: el.getAttribute("name") || "",
            href: el instanceof HTMLAnchorElement ? el.pathname : "",
            type: el.getAttribute("type") || "",
            is_search: (el.matches('input,[role="searchbox"],textarea') && /search|검색/i.test([el.type, el.name, el.id, el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.closest("form")?.getAttribute("role")].filter(Boolean).join(" "))),
            popular_keyword: popularKeywordElements.has(el),
            actionable: clickReachable,
            disabled,
            action_type: actionType,
            context_menu_hint: el.hasAttribute("oncontextmenu"),
            options: el instanceof HTMLSelectElement ? Array.from(el.options).map(option => option.textContent.trim()).filter(Boolean).slice(0, 30) : [],
            x: Math.round(rect.left),
            y: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            in_view: inView
          });
          if (elements.length >= 250) break;
        }
        const samples = elements.map(item => ({
          element: item.element,
          label: item.label,
          x: item.x,
          y: item.y,
          width: item.width,
          height: item.height
        }));
        await new Promise(resolve => setTimeout(resolve, 1200));
        const stabilized = elements.map((item, index) => {
          const sample = samples[index];
          const rect = sample.element.isConnected ? sample.element.getBoundingClientRect() : null;
          const label = sample.element.isConnected
            ? (sample.element.getAttribute("aria-label") || sample.element.getAttribute("title") || sample.element.innerText || sample.element.getAttribute("placeholder") || sample.element.getAttribute("name") || sample.element.tagName).replace(/\s+/g, " ").trim().slice(0, 100)
            : "";
          const stable = Boolean(rect && label === sample.label && Math.abs(rect.left - sample.x) <= 3 && Math.abs(rect.top - sample.y) <= 3 && Math.abs(rect.width - sample.width) <= 3 && Math.abs(rect.height - sample.height) <= 3);
          const { element: _element, ...serializable } = item;
          return {
            ...serializable,
            label: label || item.label,
            x: rect ? Math.round(rect.left) : item.x,
            y: rect ? Math.round(rect.top) : item.y,
            width: rect ? Math.round(rect.width) : item.width,
            height: rect ? Math.round(rect.height) : item.height,
            in_view: Boolean(rect && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight),
            stable,
            actionable: Boolean(rect && sample.element.isConnected && !sample.element.matches(":disabled") &&
              !sample.element.closest('[aria-disabled="true"]') && getComputedStyle(sample.element).pointerEvents !== "none" &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight &&
              document.elementsFromPoint(
                (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2,
                (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2
              ).some(hit => hit === sample.element || sample.element.contains(hit) || hit.contains(sample.element))),
            disabled: Boolean(sample.element.matches(":disabled") || sample.element.closest('[aria-disabled="true"]'))
          };
        });
        const root = document.documentElement;
        return {
          url: location.href,
          title: document.title,
          html: root.outerHTML,
          elements: stabilized,
          popular_keywords: stabilized.filter(item => item.popular_keyword).map(item => item.label).filter(Boolean),
          viewport: {
            width: innerWidth,
            height: innerHeight,
            document_width: Math.max(root.scrollWidth, document.body?.scrollWidth || 0),
            document_height: Math.max(root.scrollHeight, document.body?.scrollHeight || 0),
            scroll_x: Math.round(scrollX),
            scroll_y: Math.round(scrollY),
            device_pixel_ratio: devicePixelRatio
          }
        };
      }
    });

    // activeTab permission is granted by this explicit toolbar click.
    const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 65 });
    const capture = { ...page, screenshot };
    const response = await fetch("http://127.0.0.1:8765/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(capture)
    });
    if (!response.ok) throw new Error(`Python 앱 응답 오류 (${response.status})`);
    msg.textContent = "화면 분석 완료. Easython 메인 창에서 안내를 확인하세요.";
  } catch (error) {
    msg.textContent = error.message || "페이지 전송에 실패했습니다.";
  } finally {
    button.disabled = false;
  }
});

loadGuideSettings();
