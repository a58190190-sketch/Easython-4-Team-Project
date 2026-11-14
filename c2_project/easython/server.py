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
from .html_inventory import inventory
from .provider import sanitize_control_metadata
from .vision import analyze_capture

class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.respond(204, {})

    def do_GET(self) -> None:
        if self.path == "/guide":
            with state_lock:
                guide = state.get("guide")
                display = state.get("display")
                transparency = state.get("guide_transparency", 10)
                navigation_active = bool(state.get("navigation_session", False))
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
        if self.path not in ("/heartbeat", "/capture-policy", "/capture", "/navigate", "/monitor", "/guide/clear", "/guide/settings"):
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
                if not isinstance(data, dict) or not isinstance(data.get("url"), str):
                    self.respond(400, {"error": "url is required"})
                    return
                old_page = state.get("capture") or {}
                old_url = urlsplit(str(old_page.get("url", "")))
                new_url = urlsplit(data["url"])
                if (old_url.scheme, old_url.netloc) != (new_url.scheme, new_url.netloc):
                    self.respond(403, {"error": "automatic navigation capture is limited to the active origin"})
                    return
                guide = state.get("guide") or {}
                display = state.get("display") or {}
                goal = str(guide.get("goal") or display.get("goal") or "").strip()[:1200]
                if not goal:
                    self.respond(200, {"ok": True, "ignored": True})
                    return
                screenshot = data.get("screenshot") if isinstance(data.get("screenshot"), str) else ""
                if not screenshot.startswith("data:image/"):
                    self.respond(400, {"error": "navigation screenshot is required"})
                    return
                viewport = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
                page = {
                    "url": data["url"][:2000], "title": str(data.get("title", ""))[:500],
                    "html_chars": 0, "controls": [], "viewport": viewport,
                    "elements": sanitize_control_metadata(data.get("elements")),
                    "has_popular_keywords": False, "popular_keywords": [],
                    "vision": analyze_capture(screenshot),
                }
                page["display_advice"] = page_display_advice(page)
                page["scroll_hints"] = page_scroll_hints(page)
                state["capture"] = page
                state["guide"] = None
                state["display"] = None
                state["monitor_signature"] = ""
                state["monitor_at"] = 0.0
                state["capture_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                data.pop("screenshot", None)
                ui_events.put(("capture", (page.copy(), goal)))
                self.respond(200, {"ok": True, "analyzing": True})
                return
            elif self.path == "/monitor":
                display = state.get("display") or {}
                if not display.get("monitoring") or not isinstance(data, dict):
                    self.respond(200, {"ok": True, "ignored": True})
                    return
                incoming_url = urlsplit(str(data.get("url", "")))
                captured_url = urlsplit(str((state.get("capture") or {}).get("url", "")))
                if (incoming_url.scheme, incoming_url.netloc, incoming_url.path) != (captured_url.scheme, captured_url.netloc, captured_url.path):
                    self.respond(200, {"ok": True, "ignored": True})
                    return
                screenshot = data.get("screenshot") if isinstance(data.get("screenshot"), str) else ""
                if not screenshot.startswith("data:image/"):
                    self.respond(400, {"error": "monitor screenshot is required"})
                    return
                viewport = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
                elements = sanitize_control_metadata(data.get("elements"))
                raw_html = data.get("html") if isinstance(data.get("html"), str) else ""
                signature = json.dumps({
                    "scroll": [viewport.get("scroll_x", 0), viewport.get("scroll_y", 0)],
                    "elements": [(item.get("label"), item.get("x"), item.get("y"), item.get("in_view")) for item in elements],
                }, ensure_ascii=False, separators=(",", ":"))
                now = time.monotonic()
                has_html_fallback = bool(raw_html)
                if not has_html_fallback and (signature == state.get("monitor_signature") or now - float(state.get("monitor_at", 0.0)) < 10.0):
                    self.respond(200, {"ok": True, "checked": True, "analyzing": False})
                    return
                page = dict(state.get("capture") or {})
                page.update({"viewport": viewport, "elements": elements})
                if has_html_fallback:
                    page["controls"] = inventory(raw_html)
                    page["html_chars"] = len(raw_html)
                    page["html_fallback"] = True
                page["vision"] = analyze_capture(screenshot)
                page["display_advice"] = page_display_advice(page)
                page["scroll_hints"] = page_scroll_hints(page)
                state["capture"] = page
                state["monitor_signature"] = signature
                state["monitor_at"] = now
                if has_html_fallback:
                    state["display"] = {**display, "need_html_fallback": False}
                data.pop("html", None)
                data.pop("screenshot", None)
                raw_html = ""
                current_display = state.get("display") or display
                ui_events.put(("capture", (page.copy(), str(current_display.get("goal", "")))))
                self.respond(200, {"ok": True, "checked": True, "analyzing": True})
                return
            elif self.path == "/capture":
                if not isinstance(data, dict) or not isinstance(data.get("url"), str):
                    self.respond(400, {"error": "url is required"})
                    return
                goal = str(data.get("goal", "")).strip()[:1200]
                if not goal:
                    self.respond(400, {"error": "goal is required"})
                    return
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
                state["monitor_signature"] = ""
                state["monitor_at"] = 0.0
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
