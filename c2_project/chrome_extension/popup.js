const msg = document.getElementById("msg");
const button = document.getElementById("send");

button.addEventListener("click", async () => {
  button.disabled = true;
  msg.textContent = "현재 화면과 UI 요소를 분석 중…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || "")) {
      throw new Error("일반 http/https 웹페이지에서 실행해 주세요.");
    }

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
          'button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="searchbox"]'
        ));
        const candidates = Array.from(new Set([...baseCandidates, ...popularKeywordElements]));
        const elements = [];
        for (const el of candidates) {
          const style = getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) continue;
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
            x: Math.round(rect.left),
            y: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            in_view: rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight
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
            stable
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

fetch("http://127.0.0.1:8765/heartbeat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: "{}"
}).catch(() => {});
