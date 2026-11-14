"""Structured AI guidance response and its validation.

The model is asked to answer with ONE JSON object instead of free text that is
parsed with regular expressions. Status values:

- next        : 화면의 요소 하나를 안내한다 (target_id 필수)
- ask         : 결과가 갈리는 선택을 사용자에게 묻는다 (options 2~4개, 각자 target_id)
- user_input  : 사용자가 직접 입력해야 한다 (target_id = 입력란)
- blocked     : 외부 인증·권한 등으로 지금은 안내를 이어갈 수 없다
- done        : 목표가 달성되었다

Validation is strict on purpose: anything that points at an element not on the
current screen is dropped, so the model cannot invent UI. Wiring this into the
prompt and the guide flow happens in step 2.
"""
from __future__ import annotations
import json
import re
from typing import Any

STATUSES = ("next", "ask", "user_input", "blocked", "done")
MAX_SAY_CHARS = 120
MAX_OPTIONS = 4

RESPONSE_FORMAT_INSTRUCTION = (
    "응답은 설명 없이 JSON 객체 하나만 출력한다. 형식: "
    '{"status": "next|ask|user_input|blocked|done", '
    '"say": "사용자에게 보여줄 한 문장 행동 지침", '
    '"target_id": "visible_elements의 id", '
    '"input_hint": "user_input일 때 입력할 내용 설명(값 자체는 쓰지 않음)", '
    '"question": "ask일 때 질문", '
    '"options": [{"label": "선택지", "target_id": "id", "recommended": false}], '
    '"risk": false, '
    '"completion_hint": "목표 달성을 알아볼 화면 단서"}. '
    "선택이 하나뿐이거나 일반적인 추천이 있으면 ask 대신 next로 추천 항목을 안내한다. "
    "여러 방법 중 하나를 추천해 next로 안내할 때는 options에 화면의 다른 방법들도 함께 넣고 추천 항목에 recommended=true를 단다"
    "(사용자가 '다른 방법 보기'로 바꿀 수 있다). "
    "ask는 결과가 크게 달라지고 목표·이전 답변·추천으로 정할 수 없을 때만 쓴다."
)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object in `text` (tolerates ```json fences and chatter)."""
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(cleaned[start:index + 1])
                    except ValueError:
                        break
                    if isinstance(value, dict):
                        return value
                    break
        start = cleaned.find("{", start + 1)
    return None


def _one_sentence(value: Any, limit: int = MAX_SAY_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # Keep the first sentence only: the overlay shows one instruction at a time.
    match = re.match(r"(.+?[.!?。])(\s|$)", text)
    if match:
        text = match.group(1)
    return text[:limit]


def validate_guidance(
    raw: dict[str, Any] | None,
    elements: list[dict[str, Any]],
    *,
    questions_asked: int = 0,
    max_questions: int = 3,
) -> dict[str, Any] | None:
    """Normalise a model response against the elements actually on screen.

    Returns None when the response is unusable (caller falls back / retries).
    An `ask` over the question budget, or with fewer than two valid options,
    is downgraded to `next` on the recommended (or first) option.
    """
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status", "")).strip().lower()
    if status not in STATUSES:
        return None
    # Any element captured from the page is a valid target, including ones scrolled
    # out of view (the overlay then shows a scroll arrow toward it). Ids the model
    # invents are rejected.
    visible = {
        str(element.get("id", "")): element
        for element in elements
        if str(element.get("id", ""))
    }
    result: dict[str, Any] = {
        "status": status,
        "say": _one_sentence(raw.get("say")),
        "target_id": "",
        "target_label": "",
        "input_hint": _one_sentence(raw.get("input_hint")),
        "question": "",
        "options": [],
        "risk": raw.get("risk") is True,
        "completion_hint": _one_sentence(raw.get("completion_hint"), 160),
    }

    def bind_target(target_id: Any) -> bool:
        key = str(target_id or "")
        element = visible.get(key)
        if not element:
            return False
        result["target_id"] = key
        result["target_label"] = re.sub(r"\s+", " ", str(element.get("label", ""))).strip()[:100]
        return True

    def parse_options() -> list[dict[str, Any]]:
        options = []
        seen: set[str] = set()
        for option in raw.get("options") or []:
            if not isinstance(option, dict):
                continue
            key = str(option.get("target_id") or "")
            label = _one_sentence(option.get("label"), 60)
            if key in seen or key not in visible or not label:
                continue
            seen.add(key)
            options.append({"label": label, "target_id": key, "recommended": option.get("recommended") is True})
            if len(options) >= MAX_OPTIONS:
                break
        return options

    if status == "ask":
        options = parse_options()
        if len(options) >= 2 and questions_asked < max_questions:
            result["question"] = _one_sentence(raw.get("question")) or "어떤 것을 선택하시겠어요?"
            result["options"] = options
            result["say"] = result["say"] or result["question"]
            return result
        if not options:
            return None
        # Over budget or only one real option: recommend instead of asking, but
        # keep the other choices so the card can offer "다른 방법 보기".
        chosen = next((option for option in options if option["recommended"]), options[0])
        result["status"] = "next"
        bind_target(chosen["target_id"])
        result["say"] = f"‘{chosen['label']}’을(를) 추천해요. 이 버튼을 눌러 주세요."
        result["question"] = _one_sentence(raw.get("question")) or "어떤 방법으로 하시겠어요?"
        if len(options) >= 2:
            result["options"] = [{**option, "recommended": option["target_id"] == chosen["target_id"]} for option in options]
        return result

    if status in ("next", "user_input"):
        if not bind_target(raw.get("target_id")):
            return None
        if not result["say"]:
            result["say"] = (f"‘{result['target_label']}’ 칸에 직접 입력해 주세요." if status == "user_input"
                             else f"‘{result['target_label']}’을(를) 눌러 주세요.")
        # A recommended choice may come with the alternatives on screen; the card
        # then shows "다른 방법 보기" (switching needs no AI call).
        options = parse_options() if status == "next" else []
        if len(options) >= 2 and any(option["target_id"] == result["target_id"] for option in options):
            result["question"] = _one_sentence(raw.get("question")) or "어떤 방법으로 하시겠어요?"
            result["options"] = [{**option, "recommended": option["target_id"] == result["target_id"]} for option in options]
        return result

    # blocked / done carry no target; they need a message for the user.
    if not result["say"]:
        result["say"] = "목표를 달성했어요." if status == "done" else "이 단계는 직접 진행해 주세요."
    return result
