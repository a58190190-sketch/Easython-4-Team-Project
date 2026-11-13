let monitorCaptureBusy = false;

function originOf(url) {
  try { return new URL(url).origin; } catch (_) { return ""; }
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "EASYTHON_SESSION_START" || !Number.isInteger(message.tabId)) return;
  const origin = originOf(message.url);
  if (!origin) return;
  chrome.storage.session.set({ ["easython-session-" + message.tabId]: { origin, url: message.url, goal: message.goal } });
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "EASYTHON_SESSION_STATE" || !sender.tab?.id) return;
  const key = "easython-session-" + sender.tab.id;
  if (!message.active) {
    chrome.storage.session.remove(key);
    return;
  }
  const origin = originOf(sender.tab.url || "");
  if (origin) chrome.storage.session.set({ [key]: { origin, url: sender.tab.url, goal: message.goal || "" } });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  (async () => {
    const key = "easython-session-" + tabId;
    const stored = await chrome.storage.session.get(key);
    const session = stored[key];
    if (!session) return;
    if (originOf(tab.url) !== session.origin) {
      await chrome.storage.session.remove(key);
      return;
    }
    if (tab.url === session.url) return;
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      await chrome.storage.session.set({ [key]: { ...session, url: tab.url } });
    } catch (_) {
      // Chrome can revoke activeTab access after a cross-origin navigation.
    }
  })();
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!["EASYTHON_MONITOR_CAPTURE", "EASYTHON_NAVIGATE_CAPTURE"].includes(message?.type) || monitorCaptureBusy || !sender.tab?.windowId) return;
  monitorCaptureBusy = true;
  (async () => {
    try {
      const [activeTab] = await chrome.tabs.query({ active: true, windowId: sender.tab.windowId });
      if (activeTab?.id !== sender.tab.id) return;
      const screenshot = await chrome.tabs.captureVisibleTab(sender.tab.windowId, { format: "jpeg", quality: 55 });
      const endpoint = message.type === "EASYTHON_NAVIGATE_CAPTURE" ? "/navigate" : "/monitor";
      await fetch("http://127.0.0.1:8765" + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: message.url,
          title: message.title,
          viewport: message.viewport,
          elements: message.elements,
          screenshot
        })
      });
    } catch (_) {
      // Monitoring is best-effort and only runs while a no-target guide is active.
    } finally {
      monitorCaptureBusy = false;
    }
  })();
  return false;
});
