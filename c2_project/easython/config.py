"""Shared runtime settings and process state."""
from __future__ import annotations
import queue
import threading
from collections import deque
from typing import Any

HOST, PORT = "127.0.0.1", 8765
NIM_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_PROVIDER = "NVIDIA NIM"
PROVIDER_CONFIG = {
    "NVIDIA NIM": {"endpoint": NIM_CHAT_URL, "default_model": DEFAULT_MODEL, "key_user": "nvidia_nim_api_key", "key_label": "NVIDIA NIM API 키", "key_url": "https://build.nvidia.com/z-ai/glm-5-3-flash/build"},
    "Groq": {"endpoint": GROQ_CHAT_URL, "default_model": "openai/gpt-oss-20b", "key_user": "groq_api_key", "key_label": "Groq API 키", "key_url": "https://console.groq.com/keys"},
}
MAX_BODY = 12_000_000
KEYRING_SERVICE = "Easython"
NIM_REQUESTS_PER_MINUTE = 6
NIM_ESTIMATED_TOKENS_PER_MINUTE = 20_000
MAX_CONTEXT_CHARS = 15_000
# Only the Chrome extension may talk to the local bridge. Web pages cannot send
# this custom header cross-origin (it forces a CORS preflight the server rejects).
CLIENT_HEADER = "X-Easython-Client"
CLIENT_HEADER_VALUE = "extension"
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
# `session` holds the active GuideSession (see session.py); None when idle.
state: dict[str, Any] = {"last_seen": 0.0, "capture": None, "capture_at": None, "guide": None, "display": None, "guide_transparency": 10, "planned_route": "", "route_position": "", "accessibility_check": False, "analyzed_sites": set(), "monitor_signature": "", "monitor_at": 0.0, "session": None, "last_session": None, "step_signature": "", "analysis_status": {"busy": False, "progress": 0, "phase": "분석 대기"}}
# Re-entrant so session helpers can lock even when the HTTP handler already holds it.
state_lock = threading.RLock()
ui_events: queue.Queue[tuple[str, Any]] = queue.Queue()
guide_counter = 0
nim_rate_lock = threading.Lock()
nim_rate_events: deque[tuple[float, int]] = deque()
