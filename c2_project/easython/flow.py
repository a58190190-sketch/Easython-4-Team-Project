"""Turn a validated AI response (schema.validate_guidance) into the on-page guide.

Statuses and what the overlay does with them:
- next        : highlight one element, say one sentence
- user_input  : highlight an input; the user types, Enter/blur triggers the next step
- ask         : show a question with option buttons (choosing needs no AI call)
- blocked     : show what the user must do elsewhere (e.g. phone authentication)
- done        : goal reached; the session ends, the card offers "아직 안 끝났어요"
"""
from __future__ import annotations
import re
from typing import Any
from urllib.parse import urlsplit
from .config import state, state_lock
from . import session as sessions

_guide_counter = 0


def page_key_for(url: str) -> str:
    """Page identity shared with content.js: origin + path (+ '#/route' for hash SPAs)."""
    parsed = urlsplit(str(url or ""))
    key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.fragment.startswith("/"):
        key += "#" + parsed.fragment
    return key


def _next_id() -> int:
    global _guide_counter
    _guide_counter += 1
    return _guide_counter


def target_fields(element: dict[str, Any]) -> dict[str, Any]:
    """Everything content.js needs to find the element again after re-renders."""
    return {
        "target_id": str(element.get("id", ""))[:40],
        "label": re.sub(r"\s+", " ", str(element.get("label", ""))).strip()[:100],
        "tag": str(element.get("tag", ""))[:30],
        "role": str(element.get("role", ""))[:40],
        "type": str(element.get("type", ""))[:40],
        "aria_label": str(element.get("aria_label", ""))[:100],
        "title": str(element.get("title", ""))[:100],
        "placeholder": str(element.get("placeholder", ""))[:100],
        "name": str(element.get("name", ""))[:100],
        "href": str(element.get("href", ""))[:300],
        "click_detection": str(element.get("click_detection", ""))[:40],
        "x": element.get("x", 0),
        "y": element.get("y", 0),
        "in_view": bool(element.get("in_view", False)),
        "stable": bool(element.get("stable", False)),
        "info_region": bool(element.get("info_region", False)),
    }


def build_guide(page: dict[str, Any], response: dict[str, Any], goal: str) -> dict[str, Any]:
    """Guide payload served on GET /guide and drawn by content.js."""
    by_id = {str(element.get("id", "")): element for element in page.get("elements", [])}
    say = response.get("say", "")
    guide: dict[str, Any] = {
        "id": _next_id(),
        "page_key": page_key_for(page.get("url", "")),
        "status": response["status"],
        "say": say,
        "input_hint": response.get("input_hint", ""),
        "question": response.get("question", ""),
        "options": [],
        "risk": bool(response.get("risk")),
        "goal": goal[:160],
        "target_id": "",
        "label": "",
        # Kept for the legacy card renderer and the desktop transcript.
        "action_text": say,
        "action_card_text": say + (f"\n{response['input_hint']}" if response.get("input_hint") else ""),
        "has_visible_actionable_ui": True,
    }
    element = by_id.get(response.get("target_id", ""))
    if element:
        guide.update(target_fields(element))
    for option in response.get("options", []):
        option_element = by_id.get(option["target_id"])
        if option_element:
            guide["options"].append({
                "label": option["label"],
                "recommended": bool(option.get("recommended")),
                "target": target_fields(option_element),
            })
    return guide


def apply_response(page: dict[str, Any], response: dict[str, Any], goal: str) -> dict[str, Any]:
    """Store the guide, update the session, and return it. Ends the session on done."""
    session = sessions.current_session()
    if session and response.get("completion_hint") and not session.completion_hint:
        session.completion_hint = response["completion_hint"]
    if response["status"] in ("next", "user_input") and session:
        within_budget = sessions.record_step(
            str(page.get("url", "")), str(page.get("title", "")),
            action=response.get("say", ""), target_id=response.get("target_id", ""),
            target_label=response.get("target_label", ""),
        )
        if not within_budget:
            response = {**response, "status": "blocked", "target_id": "", "options": [],
                        "say": "안내 단계가 너무 길어졌어요. 하고 싶은 일을 다시 입력해 주세요."}
    if response["status"] == "ask" and session:
        session.questions_asked += 1
    guide = build_guide(page, response, goal)
    with state_lock:
        state["guide"] = guide
        state["display"] = None
    if response["status"] == "done":
        sessions.stop_session(sessions.DONE)
    return guide


def choose_option(guide_id: int, option_index: Any) -> dict[str, Any] | None:
    """User answered an `ask` card: guide to the chosen element without an AI call.

    option_index may be an int or "unknown" ("잘 모르겠어요" → recommended/first option).
    """
    with state_lock:
        guide = state.get("guide") or {}
        if guide.get("id") != guide_id or guide.get("status") != "ask" or not guide.get("options"):
            return None
        options = guide["options"]
        if option_index == "unknown":
            chosen = next((option for option in options if option.get("recommended")), options[0])
            say = f"‘{chosen['label']}’을(를) 추천해요. 이 버튼을 눌러 주세요."
        elif isinstance(option_index, int) and not isinstance(option_index, bool) and 0 <= option_index < len(options):
            chosen = options[option_index]
            say = f"‘{chosen['label']}’을(를) 눌러 주세요."
        else:
            return None
        session = sessions.current_session()
        if session:
            question = str(guide.get("question", "선택"))[:80]
            session.answers[question] = chosen["label"]
        new_guide = {
            **guide,
            **chosen["target"],
            "id": _next_id(),
            "status": "next",
            "say": say,
            "question": "",
            "options": [],
            "action_text": say,
            "action_card_text": say,
        }
        state["guide"] = new_guide
        return new_guide


def show_alternatives(guide_id: int) -> dict[str, Any] | None:
    """"다른 방법 보기" on a recommendation: turn it into a question card locally.

    The user asked for it, so it does not count against the question budget,
    and no AI call is made; choosing then goes through choose_option().
    """
    with state_lock:
        guide = state.get("guide") or {}
        if guide.get("id") != guide_id or guide.get("status") != "next" or len(guide.get("options") or []) < 2:
            return None
        question = guide.get("question") or "어떤 방법으로 하시겠어요?"
        new_guide = {
            **guide,
            "id": _next_id(),
            "status": "ask",
            "question": question,
            "say": question,
            "target_id": "",
            "label": "",
            "action_text": question,
            "action_card_text": question,
        }
        state["guide"] = new_guide
        return new_guide


def reopen_session() -> bool:
    """User said the goal is not finished yet: reactivate the last session."""
    with state_lock:
        last = state.get("last_session")
        if not isinstance(last, sessions.GuideSession):
            return False
        last.status = sessions.ACTIVE
        last.answers["사용자 확인"] = "아직 목표를 달성하지 못했다고 답함"
        state["session"] = last
        state["guide"] = None
        return True


def dismiss_guide() -> None:
    with state_lock:
        state["guide"] = None
        state["display"] = None


def status_guide(page_url: str, status: str, say: str, goal: str = "") -> dict[str, Any]:
    """A card without a target (analysis failure, waiting, etc.)."""
    guide = build_guide({"url": page_url, "elements": []}, {"status": status, "say": say}, goal)
    with state_lock:
        state["guide"] = guide
        state["display"] = None
    return guide
