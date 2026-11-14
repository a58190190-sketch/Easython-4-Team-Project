const msg = document.getElementById("msg");
const button = document.getElementById("send");
const goalInput = document.getElementById("goal");
const opacity = document.getElementById("opacity");
const opacityValue = document.getElementById("opacityValue");
const analysisProgress = document.getElementById("analysisProgress");
const analysisPercent = document.getElementById("analysisPercent");
const analysisPhase = document.getElementById("analysisPhase");
const BRIDGE = "http://127.0.0.1:8765";
const CLIENT_HEADERS = { "Content-Type": "application/json", "X-Easython-Client": "extension" };
// Optional "all sites" access lets the guide follow the user to the next page,
// another site (e.g. a library or login site) or a newly opened tab.
const SITE_ACCESS = { origins: ["<all_urls>"] };
let siteAccessGranted = false;
let opacityTimer = null;

function bridgeFetch(path, options = {}) {
  return fetch(BRIDGE + path, { cache: "no-store", ...options, headers: { ...CLIENT_HEADERS, ...(options.headers || {}) } });
}

goalInput.value = localStorage.getItem("easython-goal") || "";
goalInput.addEventListener("input", () => localStorage.setItem("easython-goal", goalInput.value));
goalInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    button.click();
  }
});

async function loadGuideSettings() {
  try {
    siteAccessGranted = await chrome.permissions.contains(SITE_ACCESS);
  } catch (_) {
    siteAccessGranted = false;
  }
  try {
    bridgeFetch("/heartbeat", { method: "POST", body: "{}" }).catch(() => {});
    const response = await bridgeFetch("/guide");
    if (!response.ok) return;
    const data = await response.json();
    renderAnalysisStatus(data.analysis);
    opacity.value = String(data.transparency ?? 10);
    opacityValue.value = opacity.value + "%";
    msg.textContent = siteAccessGranted
      ? "목표를 달성할 때까지 다음 페이지와 새 탭에서도 안내를 이어갑니다."
      : "버튼을 누르면 페이지를 옮겨도 안내를 이어갈 수 있도록 사이트 접근 권한을 한 번 요청합니다.";
  } catch (_) {
    msg.textContent = "Python 앱을 먼저 실행하세요.";
  }
}

function renderAnalysisStatus(status) {
  if (!status || typeof status !== "object") {
    analysisProgress.removeAttribute("value");
    analysisPercent.textContent = "상태 대기";
    analysisPhase.textContent = "앱에서 분석 상태를 받으면 여기에 표시합니다.";
    return;
  }
  const progress = Math.max(0, Math.min(100, Number(status.progress) || 0));
  const phase = String(status.phase || (status.busy ? "분석 중" : "분석 대기"));
  if (status.busy && status.indeterminate) {
    analysisProgress.removeAttribute("value");
    analysisPercent.textContent = `예상 ${progress}%`;
  } else {
    analysisProgress.value = progress;
    analysisPercent.textContent = `${progress}%`;
  }
  analysisPhase.textContent = phase;
}

async function pollAnalysisStatus() {
  try {
    const response = await bridgeFetch("/guide");
    if (!response.ok) return;
    renderAnalysisStatus((await response.json()).analysis);
  } catch (_) {
    analysisPercent.textContent = "연결 끊김";
    analysisPhase.textContent = "Python 앱 연결을 확인하세요.";
  }
}

opacity.addEventListener("input", async () => {
  opacityValue.value = opacity.value + "%";
  clearTimeout(opacityTimer);
  opacityTimer = setTimeout(async () => {
    try {
      const response = await bridgeFetch("/guide/settings", {
        method: "POST",
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
  const goal = goalInput.value.trim();
  if (!goal) {
    msg.textContent = "먼저 수행하려는 기능을 입력하세요.";
    goalInput.focus();
    return;
  }
  // permissions.request must start synchronously inside the click (user gesture),
  // before any other await. Declining keeps the old single-page behaviour.
  const siteAccessRequest = siteAccessGranted
    ? Promise.resolve(true)
    : chrome.permissions.request(SITE_ACCESS).catch(() => false);
  button.disabled = true;
  msg.textContent = "현재 화면과 입력한 기능을 앱으로 전송 중…";
  try {
    siteAccessGranted = await siteAccessRequest;
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || "")) {
      throw new Error("일반 http/https 웹페이지에서 실행해 주세요.");
    }
    const policyResponse = await bridgeFetch("/capture-policy", {
      method: "POST",
      body: JSON.stringify({ url: tab.url, goal })
    });
    if (!policyResponse.ok) throw new Error("수집 범위를 확인하지 못했습니다. Python 앱 연결을 확인하세요.");
    const capturePolicy = await policyResponse.json();
    msg.textContent = capturePolicy.need_full_html
      ? "첫 분석이므로 HTML을 확인하고 화면을 OpenCV로 분석 중…"
      : capturePolicy.need_screenshot
        ? "현재 화면 UI와 시각 분석 정보를 수집 중…"
        : "현재 화면의 UI 요소만 확인 중…";

    // activeTab is granted for this page after the user opens this extension popup.
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    const [{ result: page }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      args: [capturePolicy, goal],
      func: async (policy, requestedGoal) => {
        const hitTargetsElement = (element, rect) => {
          const insetX = Math.min(6, rect.width / 4);
          const insetY = Math.min(6, rect.height / 4);
          const xs = [rect.left + insetX, rect.left + rect.width / 2, rect.right - insetX];
          const ys = [rect.top + insetY, rect.top + rect.height / 2, rect.bottom - insetY];
          return xs.some(x => ys.some(y =>
            x >= 0 && y >= 0 && x < innerWidth && y < innerHeight &&
            document.elementsFromPoint(x, y).some(hit => hit === element || element.contains(hit) || hit.contains(element))
          ));
        };
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
          'button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[tabindex],[contenteditable="true"],[onclick],[oncontextmenu]'
        ));
        // Many sites implement clicks on plain DIV/SPAN elements (often via a
        // delegated framework handler), so include visible pointer-cursor roots.
        const pointerCandidates = [];
        const pageNodes = document.querySelectorAll("body *");
        let inspected = 0;
        for (const el of pageNodes) {
          if (++inspected > 3000 || pointerCandidates.length >= 100) break;
          if (el.matches('button,a,input,select,textarea,[role],[tabindex],[contenteditable="true"],[onclick],[oncontextmenu]')) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 8 || rect.height < 8 || rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight) continue;
          if (getComputedStyle(el).cursor !== "pointer") continue;
          let pointerAncestor = false;
          for (let parent = el.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
            if (parent.matches('button,a,[role],[onclick],[oncontextmenu]')) { pointerAncestor = true; break; }
            if (getComputedStyle(parent).cursor === "pointer") { pointerAncestor = true; break; }
          }
          if (!pointerAncestor) pointerCandidates.push(el);
        }
        const candidates = Array.from(new Set([
          ...(policy.include_popular_keywords ? popularKeywordElements : []),
          ...pointerCandidates,
          ...baseCandidates
        ])).filter(el => policy.include_popular_keywords || !popularKeywordElements.has(el));
        const elements = [];
        const hoverProbeCandidates = [];
        const interactiveSelector = 'button,a[href],input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[onclick]';
        for (const el of candidates) {
          const style = getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) continue;
          const disabled = Boolean(el.matches(":disabled") || el.closest('[aria-disabled="true"]'));
          const inView = rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
          const pointerReachable = inView && hitTargetsElement(el, rect);
          const semanticAction = el.matches('button,a[href],input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[tabindex],[contenteditable="true"]') || el.hasAttribute("oncontextmenu");
          const likelyCustomClick = style.cursor === "pointer";
          const clickReachable = inView && !disabled && style.pointerEvents !== "none" && (semanticAction || likelyCustomClick || typeof el.onclick === "function" || el.hasAttribute("onclick")) &&
            pointerReachable;
          const hoverHandlerHints = ["onmouseover", "onmouseenter", "onpointerover", "onpointerenter"].filter(name =>
            el.hasAttribute(name) || typeof el[name] === "function"
          );
          if (pointerReachable && !clickReachable && hoverProbeCandidates.length < 30) hoverProbeCandidates.push(el);
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
            click_detection: semanticAction ? "semantic" : likelyCustomClick ? "pointer_cursor_heuristic" : "event_attribute",
            hover_handler_hints: hoverHandlerHints,
            hover_reveals: [],
            hover_actionable: false,
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
        const describeVisibleInteractions = () => Array.from(document.querySelectorAll(interactiveSelector))
          .filter(el => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0 ||
              rect.width < 2 || rect.height < 2 || rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight) return false;
            const x = (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2;
            const y = (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2;
            return document.elementsFromPoint(x, y).some(hit => hit === el || el.contains(hit) || hit.contains(el));
          })
          .map(el => ({
            node: el,
            label: (el.getAttribute("aria-label") || el.getAttribute("title") || el.innerText || el.getAttribute("placeholder") || el.getAttribute("name") || el.tagName).replace(/\s+/g, " ").trim().slice(0, 100),
            signature: `${el.tagName}:${el.id}:${el.getAttribute("role") || ""}:${el.getAttribute("aria-label") || ""}:${el.innerText || ""}`.slice(0, 240)
          }));
        for (const el of hoverProbeCandidates) {
          const beforeHover = new Set(describeVisibleInteractions().map(item => item.signature));
          const rect = el.getBoundingClientRect();
          const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2));
          const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height / 2));
          const hoverEvents = ["pointerover", "pointerenter", "mouseover", "mouseenter"];
          for (const type of hoverEvents) {
            const EventClass = type.startsWith("pointer") ? PointerEvent : MouseEvent;
            el.dispatchEvent(new EventClass(type, { bubbles: true, composed: true, clientX: x, clientY: y, pointerType: "mouse" }));
          }
          await new Promise(resolve => setTimeout(resolve, 90));
          const revealed = describeVisibleInteractions()
            .filter(item => !beforeHover.has(item.signature) && item.node !== el && !item.node.matches(":disabled") && !item.node.closest('[aria-disabled="true"]'))
            .map(item => item.label).filter(Boolean).slice(0, 8);
          const ownHandlers = ["onmouseover", "onmouseenter", "onpointerover", "onpointerenter"].filter(name =>
            el.hasAttribute(name) || typeof el[name] === "function"
          );
          const index = elements.findIndex(item => item.element === el);
          if (index >= 0) {
            elements[index].hover_events = hoverEvents.filter((_, eventIndex) => eventIndex % 2 === 0);
            elements[index].hover_handler_hints = Array.from(new Set([...elements[index].hover_handler_hints, ...ownHandlers]));
            elements[index].hover_reveals = revealed;
            elements[index].hover_actionable = revealed.length > 0;
          }
          el.dispatchEvent(new PointerEvent("pointerout", { bubbles: true, composed: true, clientX: x, clientY: y, pointerType: "mouse" }));
          el.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, composed: true, clientX: x, clientY: y }));
          await new Promise(resolve => setTimeout(resolve, 40));
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
              (sample.element.matches('button,a[href],input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="searchbox"],[tabindex],[contenteditable="true"],[onclick],[oncontextmenu]') || getComputedStyle(sample.element).cursor === "pointer") &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight &&
              hitTargetsElement(sample.element, rect)),
            hover_actionable: Boolean(item.hover_actionable && rect && sample.element.isConnected &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight),
            disabled: Boolean(sample.element.matches(":disabled") || sample.element.closest('[aria-disabled="true"]'))
          };
        });
        const infoRegions = [];
        const infoIntent = /확인|보기|보여|표시|열람|읽어|목록|정보|기여자|contributors?|show|display|view|read|list/i.test(requestedGoal || "");
        const stopTerms = new Set(["현재", "화면", "사이트", "웹사이트", "정보", "내용", "목록", "전체", "모두", "확인", "보기", "표시", "읽어", "보고", "싶어요", "싶어", "해주세요", "해줘", "있는", "에서", "으로", "항목"]);
        const requestedTerms = (requestedGoal || "").toLocaleLowerCase().match(/[가-힣]{2,}|[a-z0-9]{2,}/g) || [];
        const queryTerms = requestedTerms.filter(term => !stopTerms.has(term));
        const headingNodes = infoIntent ? Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"],caption,legend,summary,[role="rowheader"],[role="columnheader"]')) : [];
        const scoredHeadings = headingNodes.map(heading => {
          const label = (heading.innerText || heading.textContent || "").replace(/\s+/g, " ").trim().slice(0, 100);
          const folded = label.toLocaleLowerCase();
          let score = queryTerms.reduce((sum, term) => sum + (folded.includes(term) ? 1 : 0), 0);
          const headingAliases = [
            [/기여자/i, /contributors?/i], [/레포지토리|저장소/i, /repository|repo/i],
            [/릴리스|출시/i, /release|changelog/i], [/공지|소식/i, /announcement|news/i],
            [/문서|가이드/i, /documentation|docs|guide/i], [/회원|멤버|구성원/i, /members?/i],
            [/이슈/i, /issues?/i], [/커밋/i, /commits?/i], [/활동/i, /activity|contributions?/i]
          ];
          for (const [goalPattern, headingPattern] of headingAliases) {
            if (goalPattern.test(requestedGoal || "") && headingPattern.test(label)) score += 2;
          }
          return { heading, label, score };
        }).filter(item => item.label && item.score > 0).sort((a, b) => b.score - a.score).slice(0, 6);
        for (const { heading, label } of scoredHeadings) {
          let selected = heading;
          let contentVisible = false;
          for (let parent = heading.parentElement, depth = 0; parent && depth < 6; parent = parent.parentElement, depth += 1) {
            const rect = parent.getBoundingClientRect();
            const text = (parent.innerText || "").replace(/\s+/g, " ").trim();
            const area = Math.max(0, rect.width) * Math.max(0, rect.height);
            if (rect.width <= 0 || rect.height <= 0 || rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight || area >= innerWidth * innerHeight * 0.6 || text.length > 700) continue;
            selected = parent;
            const remainingText = text.replace(label, "").trim();
            if (remainingText.length > 0) { contentVisible = true; break; }
          }
          const rect = selected.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2 || rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight) continue;
          const id = `info${infoRegions.length}`;
          selected.setAttribute("data-easython-info-id", id);
          infoRegions.push({
            id, tag: selected.tagName.toLowerCase(), label, role: "information_region",
            info_region: true, info_content_visible: contentVisible, actionable: false, hover_actionable: false,
            disabled: false, stable: true, in_view: true, click_detection: "informational_section",
            action_type: "information_region", x: Math.round(rect.left), y: Math.round(rect.top),
            width: Math.round(rect.width), height: Math.round(rect.height)
          });
        }
        const root = document.documentElement;
        return {
          url: location.href,
          ...(policy.include_title ? { title: document.title } : {}),
          ...(policy.need_full_html ? { html: root.outerHTML } : {}),
          elements: [...stabilized, ...infoRegions],
          ...(policy.include_popular_keywords ? { has_popular_keywords: popularKeywordElements.size > 0 } : {}),
          ...(policy.include_popular_keywords ? {
            popular_keywords: stabilized.filter(item => item.popular_keyword).map(item => item.label).filter(Boolean)
          } : {}),
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

    const screenshot = capturePolicy.need_screenshot
      ? await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 65 })
      : undefined;
    const capture = { ...page, ...(screenshot ? { screenshot } : {}), goal };
    const response = await bridgeFetch("/capture", {
      method: "POST",
      body: JSON.stringify(capture)
    });
    if (!response.ok) throw new Error(`Python 앱 응답 오류 (${response.status})`);
    await chrome.runtime.sendMessage({
      type: "EASYTHON_SESSION_START",
      tabId: tab.id,
      url: tab.url,
      goal
    }).catch(() => {});
    msg.textContent = siteAccessGranted
      ? "전송 완료. 목표를 달성할 때까지 페이지를 옮겨도 자동으로 안내를 이어갑니다."
      : "전송 완료. 사이트 접근 권한이 없어 이 페이지에서만 안내합니다. 페이지를 옮기면 다시 전송해 주세요.";
  } catch (error) {
    msg.textContent = error.message || "페이지 전송에 실패했습니다.";
  } finally {
    button.disabled = false;
  }
});

loadGuideSettings();
setInterval(pollAnalysisStatus, 800);
