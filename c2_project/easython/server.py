"""Local HTTP bridge for the Chrome extension."""
from __future__ import annotations
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit
from .config import *
from .guidance import (
    is_visual_info_request, page_display_advice, page_scroll_hints, page_site_key,
)
from .flow import choose_option, dismiss_guide, page_key_for, reopen_session, show_alternatives
from .html_inventory import inventory
from .provider import sanitize_control_metadata
from .session import current_goal, is_session_active
from .vision import analyze_capture

def is_extension_origin(origin: str) -> bool:
    return origin.startswith("chrome-extension://")

class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Never answer arbitrary web pages: CORS headers only for the extension.
        if is_extension_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", f"Content-Type, {CLIENT_HEADER}")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def client_allowed(self) -> bool:
        """Accept only the extension: right Host (blocks DNS rebinding), no foreign
        Origin, and the custom client header web pages cannot send cross-origin."""
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin", "")
        if origin and not is_extension_origin(origin):
            return False
        return self.headers.get(CLIENT_HEADER, "") == CLIENT_HEADER_VALUE

    def do_OPTIONS(self) -> None:
        if not is_extension_origin(self.headers.get("Origin", "")):
            self.respond(403, {"error": "forbidden"})
            return
        self.respond(204, {})

    def do_GET(self) -> None:
        if not self.client_allowed():
            self.respond(403, {"error": "forbidden"})
            return
        if self.path == "/guide":
            with state_lock:
                guide = state.get("guide")
                display = state.get("display")
                transparency = state.get("guide_transparency", 10)
                navigation_active = is_session_active()
                analysis = dict(state.get("analysis_status") or {})
            self.respond(200, {"guide": guide, "display": display, "transparency": transparency, "navigation_active": navigation_active, "analysis": analysis})
            return
        if self.path != "/status":
            self.respond(404, {"error": "not found"})
            return
        with state_lock:
            active = state["last_seen"] > 0 and time.time() - state["last_seen"] < 15
        self.respond(200, {"extension_connected": active})

    def do_POST(self) -> None:
        if not self.client_allowed():
            self.respond(403, {"error": "forbidden"})
            return
        if self.path not in ("/heartbeat", "/capture-policy", "/capture", "/navigate", "/guide/action", "/guide/clear", "/guide/settings"):
            self.respond(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.respond(413, {"error": "invalid payload size"})
                return
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.respond(400, {"error": "invalid JSON"})
            return
        with state_lock:
            state["last_seen"] = time.time()
            if self.path == "/capture-policy":
                if not isinstance(data, dict) or not isinstance(data.get("url"), str):
                    self.respond(400, {"error": "url is required"})
                    return
                goal = str(data.get("goal", ""))[:1200]
                if not goal.strip():
                    self.respond(400, {"error": "goal is required"})
                    return
                site_key = page_site_key(data["url"])
                visual_request = is_visual_info_request(goal)
                include_popular = bool(re.search(r"검색|키워드|인기", goal))
                need_full_html = site_key not in state["analyzed_sites"]
                self.respond(200, {
                    "need_full_html": need_full_html,
                    "need_screenshot": need_full_html or visual_request,
                    "include_title": need_full_html or visual_request,
                    "include_popular_keywords": include_popular,
                })
                return
            elif self.path == "/navigate":
                # Step capture from the session tab. Sent only on the triggers the
                # extension watches: URL change, a click on the guided element,
                # finished input (Enter/blur/change), return from a closed tab, or
                # the user's "다시 안내" button. There is no periodic AI polling.
                if not isinstance(data, dict) or not isinstance(data.get("url"), str):
                    self.respond(400, {"error": "url is required"})
                    return
                if urlsplit(data["url"]).scheme not in ("http", "https"):
                    self.respond(400, {"error": "http(s) url is required"})
                    return
                # Read the full goal from the session; guide["goal"] is truncated.
                goal = current_goal() if is_session_active() else ""
                if not goal:
                    self.respond(200, {"ok": True, "ignored": True})
                    return
                reason = str(data.get("reason", "url"))[:20]
                elements = sanitize_control_metadata(data.get("elements"))
                # Same URL and same visible controls after a click/input means the
                # screen did not change: keep the current guide, skip the AI call.
                signature = json.dumps({
                    "page": page_key_for(data["url"]),
                    "labels": sorted({str(item.get("label", "")) for item in elements if item.get("in_view")}),
                }, ensure_ascii=False, separators=(",", ":"))
                if reason in ("click", "input") and signature == state.get("step_signature"):
                    self.respond(200, {"ok": True, "unchanged": True})
                    return
                viewport = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
                completed_actions = [
                    item for item in (old_page.get("completed_guided_actions") or [])
                    if isinstance(item, dict)
                ]
                if guide.get("label"):
                    completed_actions.append({
                        "label": str(guide.get("label", ""))[:100],
                        "href": str(guide.get("href", ""))[:300],
                        "action_type": str(guide.get("action_type", ""))[:30],
                        "is_search": bool(guide.get("is_search", False)),
                        "search_query": str(guide.get("search_query", ""))[:200],
                    })
                completed_actions = completed_actions[-8:]
                page = {
                    "url": data["url"][:2000], "title": str(data.get("title", ""))[:500],
                    "html_chars": 0, "controls": [], "viewport": viewport,
                    "elements": elements,
                    "previous_guided_action": {
                        "label": str(guide.get("label", ""))[:100],
                        "href": str(guide.get("href", ""))[:300],
                        "action_type": str(guide.get("action_type", ""))[:30],
                        "is_search": bool(guide.get("is_search", False)),
                        "search_query": str(guide.get("search_query", ""))[:200],
                        "source_url": str(old_page.get("url", ""))[:2000],
                    } if guide else {},
                    "completed_guided_actions": completed_actions,
                    "has_popular_keywords": False, "popular_keywords": [],
                    "vision": {"ok": False, "width": int(viewport.get("width", 0) or 0),
                               "height": int(viewport.get("height", 0) or 0), "region_count": 0},
                    "capture_reason": reason,
                }
                page["display_advice"] = page_display_advice(page)
                page["scroll_hints"] = page_scroll_hints(page)
                state["capture"] = page
                state["step_signature"] = signature
                state["guide"] = None
                state["display"] = None
                state["capture_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                ui_events.put(("capture", (page.copy(), goal)))
                self.respond(200, {"ok": True, "analyzing": True})
                return
            elif self.path == "/guide/action":
                action = str(data.get("action", "")) if isinstance(data, dict) else ""
                if action == "choose":
                    option = data.get("option")
                    guide_id = data.get("guide_id")
                    if not isinstance(guide_id, int) or not (option == "unknown" or isinstance(option, int)):
                        self.respond(400, {"error": "guide_id and option are required"})
                        return
                    guide = choose_option(guide_id, option)
                    if guide:
                        ui_events.put(("guide_note", f"선택: {guide['say']}"))
                    self.respond(200, {"ok": bool(guide)})
                    return
                if action == "alternatives":
                    guide_id = data.get("guide_id")
                    guide = show_alternatives(guide_id) if isinstance(guide_id, int) else None
                    if guide:
                        ui_events.put(("guide_note", "다른 방법 보기: " + ", ".join(option["label"] for option in guide["options"])))
                    self.respond(200, {"ok": bool(guide)})
                    return
                if action == "dismiss":
                    dismiss_guide()
                    self.respond(200, {"ok": True})
                    return
                if action == "reopen":
                    reopened = reopen_session()
                    if reopened:
                        ui_events.put(("reopen", current_goal()))
                    # The extension follows up with a "retry" capture of the screen.
                    self.respond(200, {"ok": reopened})
                    return
                self.respond(400, {"error": "unknown action"})
                return
            elif self.path == "/capture":
                if not isinstance(data, dict) or not isinstance(data.get("url"), str):
                    self.respond(400, {"error": "url is required"})
                    return
                goal = str(data.get("goal", "")).strip()[:1200]
                if not goal:
                    self.respond(400, {"error": "goal is required"})
                    return
                old_page = state.get("capture") or {}
                old_guide = state.get("guide") or {}
                old_display = state.get("display") or {}
                old_goal = str(old_guide.get("goal") or old_display.get("goal") or "").strip()
                continue_external_session = bool(
                    state.get("navigation_session") and old_goal and old_goal == goal
                    and urlsplit(str(old_page.get("url", ""))).netloc.lower() != urlsplit(data["url"]).netloc.lower()
                )
                completed_actions = [
                    item for item in (old_page.get("completed_guided_actions") or [])
                    if isinstance(item, dict)
                ] if continue_external_session else []
                if continue_external_session and old_guide.get("label"):
                    completed_actions.append({
                        "label": str(old_guide.get("label", ""))[:100],
                        "href": str(old_guide.get("href", ""))[:300],
                        "action_type": str(old_guide.get("action_type", ""))[:30],
                        "is_search": bool(old_guide.get("is_search", False)),
                        "search_query": str(old_guide.get("search_query", ""))[:200],
                    })
                completed_actions = completed_actions[-8:]
                raw_html = data.get("html") if isinstance(data.get("html"), str) else ""
                screenshot = data.get("screenshot") if isinstance(data.get("screenshot"), str) else ""
                if screenshot and not screenshot.startswith("data:image/"):
                    self.respond(400, {"error": "invalid screenshot format"})
                    return
                viewport = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
                page = {
                    "url": data["url"][:2000],
                    "title": str(data.get("title", ""))[:500],
                    "html_chars": len(raw_html),
                    "html_fallback": bool(raw_html),
                    "controls": inventory(raw_html),
                    "previous_guided_action": completed_actions[-1] if completed_actions else {},
                    "completed_guided_actions": completed_actions,
                    "viewport": data.get("viewport") if isinstance(data.get("viewport"), dict) else {},
                    "elements": sanitize_control_metadata(data.get("elements")),
                    "has_popular_keywords": bool(data.get("has_popular_keywords")),
                    "popular_keywords": [str(value)[:80] for value in data.get("popular_keywords", [])[:30] if isinstance(value, str)] if isinstance(data.get("popular_keywords"), list) else [],
                }
                page["vision"] = analyze_capture(screenshot) if screenshot else {
                    "ok": False, "width": int(viewport.get("width", 0) or 0),
                    "height": int(viewport.get("height", 0) or 0), "region_count": 0,
                }
                data.pop("html", None)
                data.pop("screenshot", None)
                raw_html = ""
                screenshot = ""
                page["display_advice"] = page_display_advice(page)
                page["scroll_hints"] = page_scroll_hints(page)
                state["capture"] = page
                state["guide"] = None
                state["display"] = None
                state["step_signature"] = ""
                state["capture_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                ui_events.put(("capture", (state["capture"].copy(), goal)))
            elif self.path == "/guide/clear":
                state["guide"] = None
                state["display"] = None
            elif self.path == "/guide/settings":
                transparency = data.get("transparency") if isinstance(data, dict) else None
                if isinstance(transparency, bool) or not isinstance(transparency, int) or not 0 <= transparency <= 100:
                    self.respond(400, {"error": "transparency must be an integer from 0 to 100"})
                    return
                state["guide_transparency"] = transparency
        self.respond(200, {"ok": True})

    def log_message(self, fmt: str, *args: Any) -> None:
        return

def start_server() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
