// Background service worker: owns the guide session and every request to the
// local Python bridge. Content scripts never fetch 127.0.0.1 themselves (the
// bridge rejects web-page origins), they message this worker instead.
const BRIDGE = "http://127.0.0.1:8765";
const CLIENT_HEADERS = { "Content-Type": "application/json", "X-Easython-Client": "extension" };
const SESSION_KEY = "easython-session";
const SITE_ACCESS = { origins: ["<all_urls>"] };
let stepBusy = false;

function bridgeFetch(path, options = {}) {
  return fetch(BRIDGE + path, { cache: "no-store", ...options, headers: { ...CLIENT_HEADERS, ...(options.headers || {}) } });
}

// Session shape: { tabId, goal, url, previousTabIds: number[] }.
// One session at a time; it follows the user's tab, not a fixed origin.
async function getSession() {
  return (await chrome.storage.session.get(SESSION_KEY))[SESSION_KEY] || null;
}

async function setSession(session) {
  if (session) await chrome.storage.session.set({ [SESSION_KEY]: session });
  else await chrome.storage.session.remove(SESSION_KEY);
}

async function hasSiteAccess() {
  try { return await chrome.permissions.contains(SITE_ACCESS); } catch (_) { return false; }
}

async function injectGuide(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return true;
  } catch (_) {
    // Without the optional site permission only the page the popup was opened on
    // is reachable; after navigation Chrome revokes that temporary access.
    return false;
  }
}

// Step capture from content.js (URL change, guided click, finished input, return,
// or "다시 안내"). No screenshot: the AI only needs the element list.
async function sendStep(message, sender) {
  const session = await getSession();
  // Only the session's own tab may drive the guide; stale tabs are ignored.
  if (!session || sender.tab?.id !== session.tabId) return { sent: false, reason: "not_session_tab" };
  if (stepBusy) return { sent: false, reason: "busy" };
  stepBusy = true;
  try {
    const response = await bridgeFetch("/navigate", {
      method: "POST",
      body: JSON.stringify({
        reason: message.reason,
        url: message.url,
        title: message.title,
        viewport: message.viewport,
        elements: message.elements
      })
    });
    return { sent: response.ok, status: response.status };
  } catch (_) {
    return { sent: false, reason: "bridge_unreachable" };
  } finally {
    stepBusy = false;
  }
}

async function guideAction(message, sender) {
  const payload = { action: message.action };
  if (Number.isInteger(message.guide_id)) payload.guide_id = message.guide_id;
  if (message.action === "choose") payload.option = message.option;
  const response = await bridgeFetch("/guide/action", { method: "POST", body: JSON.stringify(payload) });
  const result = response.ok ? await response.json() : { ok: false };
  // "아직 안 끝났어요": the session ended on "done", so attach it to this tab again.
  if (message.action === "reopen" && result.ok && Number.isInteger(sender.tab?.id)) {
    await setSession({ tabId: sender.tab.id, goal: "", url: sender.tab.url || "", previousTabIds: [] });
  }
  return result;
}

async function pollGuide(sender) {
  const session = await getSession();
  const response = await bridgeFetch("/guide");
  if (!response.ok) return { ok: false };
  return {
    ok: true,
    data: await response.json(),
    // Before the popup registers a session, the page it was opened on may draw.
    sessionTab: !session || sender.tab?.id === session.tabId
  };
}

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "EASYTHON_SESSION_START": {
      if (!Number.isInteger(message.tabId)) return { ok: false };
      await setSession({ tabId: message.tabId, goal: String(message.goal || ""), url: String(message.url || ""), previousTabIds: [] });
      return { ok: true, siteAccess: await hasSiteAccess() };
    }
    case "EASYTHON_SESSION_STATE": {
      const session = await getSession();
      if (!message.active && session && sender.tab?.id === session.tabId) await setSession(null);
      return { ok: true };
    }
    case "EASYTHON_GUIDE_POLL":
      return pollGuide(sender);
    case "EASYTHON_STEP_CAPTURE":
      return sendStep(message, sender);
    case "EASYTHON_GUIDE_ACTION":
      return guideAction(message, sender);
    default:
      return undefined;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const pending = handleMessage(message, sender);
  if (!pending) return false;
  pending.then(sendResponse, () => sendResponse({ ok: false }));
  return true; // keep the channel open for the async response
});

// Page loaded (same site, another site, or a full reload) in the session tab:
// reconnect the guide there. content.js then sends a "url" step capture.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !/^https?:/.test(tab.url || "")) return;
  (async () => {
<<<<<<< HEAD
    const session = await getSession();
    if (!session || session.tabId !== tabId) return;
    await injectGuide(tabId);
    await setSession({ ...session, url: tab.url });
=======
    const key = "easython-session-" + tabId;
    const stored = await chrome.storage.session.get(key);
    const session = stored[key];
    if (!session) return;
    if (originOf(tab.url) !== session.origin) {
      // activeTab does not carry page access across origins. Keep the goal and
      // record the destination so the popup can resume after the user invokes it.
      await chrome.storage.session.set({ [key]: { ...session, pending_url: tab.url } });
      return;
    }
    if (tab.url === session.url) return;
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      await chrome.storage.session.set({ [key]: { ...session, url: tab.url } });
    } catch (_) {
      // Chrome can revoke activeTab access after a cross-origin navigation.
    }
>>>>>>> c7594d96a3fb72e7cbcfb0cf038dee7668c3606d
  })();
});

// A link or script in the session tab opened a new tab/window (e.g. the
// library site): move the session there and remember where to come back.
chrome.tabs.onCreated.addListener(tab => {
  (async () => {
    const session = await getSession();
    if (!session || !Number.isInteger(tab.id) || tab.openerTabId !== session.tabId) return;
    await setSession({ ...session, tabId: tab.id, previousTabIds: [...session.previousTabIds, session.tabId].slice(-5) });
  })();
});

// The session tab was closed (e.g. an auth popup finished): fall back to the
// most recent opener tab that still exists and re-check its screen.
chrome.tabs.onRemoved.addListener(tabId => {
  (async () => {
    const session = await getSession();
    if (!session || session.tabId !== tabId) return;
    const previous = [...session.previousTabIds];
    while (previous.length) {
      const candidate = previous.pop();
      try {
        await chrome.tabs.get(candidate);
        await setSession({ ...session, tabId: candidate, previousTabIds: previous });
        await injectGuide(candidate);
        await chrome.tabs.sendMessage(candidate, { type: "EASYTHON_FORCE_CAPTURE", reason: "return" }).catch(() => {});
        return;
      } catch (_) {
        // Tab is gone too; try the one before it.
      }
    }
    await setSession(null);
  })();
});
