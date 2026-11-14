"""Page sizing, goal parsing, and guide target selection."""
from __future__ import annotations
import re
from typing import Any
from urllib.parse import urlsplit
from .config import state, state_lock

guide_counter = 0

def page_display_advice(page: dict[str, Any]) -> str:
    viewport = page.get("viewport") or {}
    width = int(viewport.get("width", 0) or 0)
    height = int(viewport.get("height", 0) or 0)
    document_width = int(viewport.get("document_width", 0) or 0)
    document_height = int(viewport.get("document_height", 0) or 0)
    advice = []
    scroll_x = int(viewport.get("scroll_x", 0) or 0)
    scroll_y = int(viewport.get("scroll_y", 0) or 0)
    if height and document_height > height * 1.03 and scroll_y + height < document_height - 2:
        advice.append("페이지가 화면보다 깁니다. 아래 방향으로 스크롤해 화면을 이동한 뒤 다시 전송하세요.")
    elif width and document_width > width * 1.03 and scroll_x + width < document_width - 2:
        advice.append("페이지가 화면보다 넓습니다. 오른쪽 방향으로 스크롤해 화면을 이동한 뒤 다시 전송하세요.")
    elif height and document_height > height * 1.03 and scroll_y > 0:
        advice.append("페이지가 화면보다 깁니다. 위 방향으로 스크롤해 화면을 이동한 뒤 다시 전송하세요.")
    elif width and document_width > width * 1.03 and scroll_x > 0:
        advice.append("페이지가 화면보다 넓습니다. 왼쪽 방향으로 스크롤해 화면을 이동한 뒤 다시 전송하세요.")
    return " ".join(advice)

def page_scroll_hints(page: dict[str, Any]) -> list[dict[str, str]]:
    viewport = page.get("viewport") or {}
    width = int(viewport.get("width", 0) or 0)
    height = int(viewport.get("height", 0) or 0)
    document_width = int(viewport.get("document_width", 0) or 0)
    document_height = int(viewport.get("document_height", 0) or 0)
    scroll_x = int(viewport.get("scroll_x", 0) or 0)
    scroll_y = int(viewport.get("scroll_y", 0) or 0)
    hints = []
    if height and document_height > height * 1.03:
        if scroll_y + height < document_height - 2:
            hints.append({"arrow": "↓", "label": "아래쪽 방향으로 스크롤", "edge": "bottom"})
    if not hints and width and document_width > width * 1.03:
        if scroll_x + width < document_width - 2:
            hints.append({"arrow": "→", "label": "오른쪽 방향으로 스크롤", "edge": "right"})
        elif scroll_x > 0:
            hints.append({"arrow": "←", "label": "왼쪽 방향으로 스크롤", "edge": "left"})
    if not hints and height and document_height > height * 1.03 and scroll_y > 0:
        hints.append({"arrow": "↑", "label": "위쪽 방향으로 스크롤", "edge": "top"})
    return hints

def search_query_from_goal(goal: str) -> str:
    query = re.sub(r"(해주세요|해 주세요|해줘|해 줘|하고 싶어요|하고 싶습니다|찾아보기|찾아줘|찾아 주세요|검색해줘|검색해 주세요|검색|조회|출력|발급|신청|찾기|찾아)", " ", goal, flags=re.IGNORECASE)
    query = re.sub(r"^(웹사이트에서|사이트에서|포털에서|여기서)\s*", "", query.strip())
    query = re.sub(r"\s+", " ", query).strip(" \t,.:;!?·")
    query = re.sub(r"[을를은는이가]$", "", query).strip()
    return query or goal.strip()

def is_visual_info_request(goal: str) -> bool:
    asks_to_view = re.search(
        r"보여|보이|보고\s*싶|확인하고\s*싶|표시해|알려줘|알려\s*주|읽어|정리해|내용을?\s*확인|정보.{0,8}(?:확인|보기|읽어|열어)|(?:확인|보기|읽어).{0,8}정보|목록|정보를?\s*보|(?:기여자|contributors?|목록|레포지토리|repository).{0,16}(?:확인|보기|보여|표시|읽어)|(?:확인|보기|보여|표시).{0,16}(?:기여자|contributors?|목록)|show|display|view|see|read|list|what\s+are",
        goal,
        flags=re.IGNORECASE,
    )
    asks_to_act = re.search(
        r"검색|조회|출력|발급|신청|제출|삭제|수정|추가|생성|전송|저장|이동|download|submit|delete|edit|create|navigate",
        goal,
        flags=re.IGNORECASE,
    )
    return bool(asks_to_view and not asks_to_act)

def page_site_key(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc.lower()

def labeled_answer_line(answer: str, labels: tuple[str, ...]) -> str:
    cleaned = re.sub(r"[*_`#>]", "", answer)
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^\s*(?:{label_pattern})\s*[:：]\s*(.+?)\s*$", cleaned)
    return match.group(1).strip() if match else ""

def action_text_for_target(
    target: dict[str, Any], search_query: str, answer: str, goal: str, elements: list[dict[str, Any]]
) -> str:
    action_type = str(target.get("action_type", ""))
    if target.get("info_region"):
        label = re.sub(r"\s+", " ", str(target.get("label", "정보 영역"))).strip()[:100]
        return f"현재 화면의 ‘{label}’ 영역에 표시된 요청 정보를 확인하세요."
    if target.get("hover_actionable"):
        revealed = [str(label) for label in target.get("hover_reveals", []) if str(label).strip()]
        revealed_text = f" 팝업에서 ‘{revealed[0]}’ 등 표시된 항목을 확인하세요." if revealed else ""
        return "마우스를 올려 메뉴를 표시하세요." + revealed_text
    if is_visual_info_request(goal):
        current_action = labeled_answer_line(answer, ("현재 화면에서 할 동작", "현재 동작", "이번 동작"))
        label = str(target.get("label", "")).strip()
        if current_action and label and label.casefold() in current_action.casefold():
            if not re.search(r"전체|모두|전부|모든|표시|열어|펼쳐|확장|show|view all|all", current_action, re.IGNORECASE):
                current_action = current_action.rstrip(". ") + " → 요청한 정보 전체를 표시하여 확인"
            return current_action[:240]
        if label:
            return f"‘{label}’을 클릭해 요청한 정보 전체를 표시하여 확인하세요."
    if search_query:
        return f"왼쪽 클릭 1회 → ‘{search_query}’ 입력 → Enter"
    if target.get("context_menu_hint"):
        menu_items = [
            str(item.get("label", "")) for item in elements
            if item.get("in_view") and item.get("actionable") and item.get("role") == "menuitem"
        ]
        menu_item = next((item for item in menu_items if item and (item in answer or item in goal)), "")
        if menu_item:
            return f"오른쪽 클릭 1회 → 표시된 메뉴에서 ‘{menu_item}’ 선택"
    if action_type == "link":
        return "마우스 왼쪽 버튼으로 한 번 클릭해 이동"
    if action_type == "select":
        options = [str(option) for option in target.get("options", [])]
        selected = next((option for option in options if option and (option in goal or option in answer)), "")
        return f"왼쪽 클릭 후 목록에서 ‘{selected}’ 선택" if selected else "왼쪽 클릭 후 목록에서 목표에 맞는 항목 선택"
    if action_type == "toggle":
        return "마우스 왼쪽 버튼으로 한 번 클릭해 선택"
    if action_type in ("search_input", "text_input"):
        return "마우스 왼쪽 버튼으로 입력란을 클릭한 뒤 내용 입력"
    if action_type == "menu_item":
        return "마우스 왼쪽 버튼으로 한 번 클릭해 선택"
    return "마우스 왼쪽 버튼으로 한 번 클릭"

def update_page_guide(page: dict[str, Any], answer: str, goal: str) -> str:
    """Guide a visible candidate, optionally requiring verified interaction reachability."""
    global guide_counter
    visual_info_request = is_visual_info_request(goal)
    current_action = labeled_answer_line(answer, ("현재 화면에서 할 동작", "현재 동작", "이번 동작"))
    route = labeled_answer_line(answer, ("접근 경로", "이용 경로", "목표까지 경로"))
    route_position = labeled_answer_line(answer, ("현재 위치", "현재 경로 위치"))
    with state_lock:
        if visual_info_request:
            # Viewing information should stay on this page; discard a stale/model
            # route that would send the user to another tab or page.
            route = "현재 페이지에서 정보 확인"
            route_position = str(page.get("title", "현재 화면"))
            state["planned_route"] = route
            state["route_position"] = route_position
        else:
            if route:
                state["planned_route"] = route
            if route_position:
                state["route_position"] = route_position
            route = str(state.get("planned_route", ""))
            route_position = str(state.get("route_position", "")) or str(page.get("title", "현재 화면"))
        accessibility_check = bool(state.get("accessibility_check", False))
    has_visible_actionable_ui = any(
        bool(element.get("in_view")) and (bool(element.get("actionable")) or bool(element.get("hover_actionable")))
        for element in page.get("elements", [])
    )
    has_visible_candidate_ui = any(bool(element.get("in_view")) and bool(element.get("stable")) for element in page.get("elements", []))
    has_visible_guide_ui = has_visible_actionable_ui or (not accessibility_check and has_visible_candidate_ui)
    match_text = current_action or answer
    match_folded = re.sub(r"\s+", " ", match_text).casefold()
    matches = []
    for element in page.get("elements", []):
        label = re.sub(r"\s+", " ", str(element.get("label", ""))).strip()
        can_guide = bool(element.get("actionable") or element.get("hover_actionable"))
        if len(label) >= 2 and label.casefold() in match_folded and element.get("in_view") and (can_guide or not accessibility_check or element.get("info_region")):
            # Stable targets rank first, but a moving clickable control remains
            # eligible when it is the only matching visible target.
            matches.append((bool(element.get("stable")), can_guide, len(label), element))
    if visual_info_request:
        current_url = urlsplit(str(page.get("url", "")))
        current_path = current_url.path.rstrip("/") or "/"
        # Do not guide to a link that leaves the current page for a read-only
        # information request. In-page anchors and non-link expand/scroll UI
        # remain eligible.
        def stays_on_current_page(element: dict[str, Any]) -> bool:
            if element.get("info_region") or str(element.get("tag", "")).lower() != "a":
                return True
            href = str(element.get("href", "")).strip()
            if not href:
                return True
            destination = urlsplit(href)
            if destination.netloc and destination.netloc.lower() != current_url.netloc.lower():
                return False
            destination_path = destination.path.rstrip("/") or current_path
            return destination_path == current_path
        matches = [item for item in matches if stays_on_current_page(item[3])]
    matches.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    target = matches[0][3] if matches else None
    has_popular_keywords = bool(page.get("has_popular_keywords")) or any(element.get("popular_keyword") for element in page.get("elements", []))
    search_intent = bool(re.search(r"검색|찾|조회|출력|발급|신청", goal))
    search_query = search_query_from_goal(goal) if (has_popular_keywords or search_intent) and not is_visual_info_request(goal) else ""
    if (has_popular_keywords or search_intent) and not is_visual_info_request(goal):
        search_fields = [element for element in page.get("elements", []) if element.get("is_search") and element.get("in_view") and (element.get("actionable") or not accessibility_check)]
        search_fields.sort(key=lambda element: (bool(element.get("stable")), bool(element.get("actionable")), len(str(element.get("label", "")))), reverse=True)
        action_names_search = any(str(element.get("label", "")).casefold() in match_folded for element in search_fields)
        if search_fields and (target is None or target.get("is_search") or action_names_search):
            target = search_fields[0]
    parsed = urlsplit(page.get("url", ""))
    page_key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    display_hint = {
        "page_key": page_key,
        "viewport": page.get("viewport", {}),
        # The target UI is absent even if unrelated controls are visible.
        "has_visible_actionable_ui": False,
        "monitoring": True,
        "need_html_fallback": not bool(page.get("html_fallback", False)),
        "goal": goal[:1200],
        "instruction": "화면을 스크롤하거나 메뉴를 열어 필요한 UI를 표시하세요. 화면을 자동 확인하고 있습니다.",
    }
    route_note = " · ".join(part for part in (
        f"접근 경로: {route}" if route else "",
        f"현재 위치: {route_position}" if route_position else "",
    ) if part)
    if not target:
        with state_lock:
            state["guide"] = None
            state["display"] = display_hint
        if search_query:
            return f"입력할 검색어: ‘{search_query}’. {route_note} 목표 UI가 보이지 않습니다. 화면을 스크롤하거나 메뉴를 열어 필요한 UI를 표시해 주세요. 표시될 때까지 화면을 자동으로 확인합니다."
        if visual_info_request:
            return f"{route_note} 현재 화면에서 요청한 정보를 찾지 못했습니다. 다른 페이지로 이동하기 전에 현재 페이지를 스크롤하거나 ‘더 보기/펼치기’ UI를 사용해 정보를 표시해 주세요. 표시될 때까지 현재 페이지를 자동으로 확인합니다."
        if accessibility_check and has_visible_actionable_ui:
            return f"{route_note} 현재 화면에 조작 가능한 UI가 있지만 다음 경로 UI를 특정하지 못했습니다. 해당 메뉴나 옵션을 열거나 마우스를 올린 뒤 화면을 다시 전송하세요."
        if not accessibility_check and has_visible_candidate_ui:
            return f"{route_note} 현재 화면 UI 후보는 수신했지만 목표 경로에 맞는 요소를 특정하지 못했습니다. 접근성 확인 다시보기로 후보를 다시 분석할 수 있습니다."
        return f"{route_note} 목표 UI가 현재 화면에 보이지 않습니다. 화면을 스크롤하거나 메뉴를 열어 필요한 UI를 표시해 주세요. 표시될 때까지 화면을 자동으로 확인합니다."
    if not target.get("in_view"):
        with state_lock:
            state["guide"] = None
            state["display"] = display_hint
        return f"‘{target.get('label', '대상 UI')}’가 현재 화면 밖에 있습니다. 해당 영역까지 스크롤한 뒤 확장 프로그램에서 화면을 다시 전송하세요."
    with state_lock:
        guide_counter += 1
        guide = {
            "id": guide_counter,
            "page_key": page_key,
            "target_id": str(target.get("id", "")),
            "label": str(target.get("label", ""))[:100],
            "tag": str(target.get("tag", ""))[:30],
            "click_detection": str(target.get("click_detection", ""))[:40],
            "role": str(target.get("role", ""))[:40],
            "type": str(target.get("type", ""))[:40],
            "aria_label": str(target.get("aria_label", ""))[:100],
            "title": str(target.get("title", ""))[:100],
            "placeholder": str(target.get("placeholder", ""))[:100],
            "name": str(target.get("name", ""))[:100],
            "href": str(target.get("href", ""))[:300],
            "x": target.get("x", 0),
            "y": target.get("y", 0),
            "goal": goal[:160],
            "stable": bool(target.get("stable", False)),
            "info_region": bool(target.get("info_region", False)),
            "has_visible_actionable_ui": has_visible_actionable_ui,
            "planned_route": route,
            "route_position": route_position,
            "instruction": f"검색창에 ‘{search_query}’를 입력하세요" if search_query else "",
            "search_query": search_query,
            "accessibility_checked": accessibility_check,
            "action_text": (action_text_for_target(target, search_query if target.get("is_search") else "", answer, goal, page.get("elements", [])) if accessibility_check else action_text_for_target(target, search_query if target.get("is_search") else "", answer, goal, page.get("elements", []))),
            "action_card_text": (f"현재 위치: {route_position}\n" if route_position else "") + (action_text_for_target(target, search_query if target.get("is_search") else "", answer, goal, page.get("elements", [])) if accessibility_check else action_text_for_target(target, search_query if target.get("is_search") else "", answer, goal, page.get("elements", []))),
        }
        state["guide"] = guide
        state["display"] = None
    route_text = f"{route_note} · " if route_note else ""
    access_note = ("현재 화면에 표시된 정보 영역입니다. " if target.get("info_region") else
                   "접근 가능성 확인 완료. " if accessibility_check else
                   "1차 후보 안내(접근 가능성 미검사). 다시보기로 클릭·hover 접근 가능성을 확인할 수 있습니다. ")
    if search_query and target.get("is_search"):
        return f"입력할 검색어: ‘{search_query}’. {access_note}{route_text}화면에서 ‘{guide['label']}’ 위치를 표시했습니다. 수행할 동작: {guide['action_text']}."
    query_text = f"목표 검색어: ‘{search_query}’. " if search_query else ""
    return f"{query_text}{access_note}{route_text}화면에서 ‘{guide['label']}’ 위치를 표시했습니다. 수행할 동작: {guide['action_text']}."

def visible_information_answer(page: dict[str, Any], goal: str) -> str | None:
    """Return a direct, label-specific instruction for information already visible."""
    if not is_visual_info_request(goal):
        return None
    regions = [
        element for element in page.get("elements", [])
        if element.get("info_region") and element.get("info_content_visible") and element.get("in_view")
    ]
    if not regions:
        return None

    ignored_terms = {
        "현재", "화면", "사이트", "웹사이트", "정보", "내용", "목록", "전체", "모두",
        "확인", "보기", "보여줘", "보여", "표시", "읽어", "보고", "싶어", "싶어요",
        "해주세요", "해줘", "부탁", "관련", "항목", "있는", "에서", "으로", "에게",
    }
    terms = [
        term.casefold() for term in re.findall(r"[가-힣]{2,}|[a-z0-9]{2,}", goal, re.IGNORECASE)
        if term.casefold() not in ignored_terms
    ]
    if not terms:
        return None

    aliases = (
        (r"기여자", ("contributor", "기여자")),
        (r"레포지토리|저장소", ("repository", "repo", "저장소")),
        (r"릴리스|출시", ("release", "changelog", "릴리스")),
        (r"공지|소식", ("announcement", "news", "공지")),
        (r"문서|가이드", ("documentation", "docs", "guide", "문서")),
        (r"회원|멤버|구성원", ("member", "members", "구성원")),
        (r"이슈", ("issue", "issues", "이슈")),
        (r"커밋", ("commit", "commits", "커밋")),
        (r"활동", ("activity", "contribution", "활동")),
    )

    def relevance(region: dict[str, Any]) -> tuple[int, bool, int]:
        label = re.sub(r"\s+", " ", str(region.get("label", ""))).strip()
        folded_label = label.casefold()
        score = sum(1 for term in terms if term in folded_label or folded_label in term)
        for pattern, words in aliases:
            if re.search(pattern, goal, re.IGNORECASE) and any(word.casefold() in folded_label for word in words):
                score += 2
        return score, bool(region.get("stable", False)), len(label)

    visible_region = max(regions, key=relevance)
    score, _stable, _length = relevance(visible_region)
    # The extension only sends regions it matched against this goal. If it found
    # exactly one visible content region, its dynamic heading is an adequate match.
    if score <= 0 and len(regions) != 1:
        return None
    label = re.sub(r"\s+", " ", str(visible_region.get("label", ""))).strip()[:100]
    if not label:
        return None
    return f"현재 화면에서 할 동작: ‘{label}’ 영역에 표시된 요청 정보를 확인하세요."
