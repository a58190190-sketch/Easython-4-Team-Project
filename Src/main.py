"""A small Streamlit MVP for tracking weekly climate actions."""

from __future__ import annotations

import json
import calendar
from datetime import date, timedelta
from pathlib import Path
import os

import streamlit as st


GOALS = {
    "tumbler": "텀블러 사용하기",
    "transit": "대중교통 이용하기",
    "plogging": "플로깅하기",
}
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash"]
DATA_FILE = Path(__file__).with_name("planner_data.json")


def load_records() -> dict[str, dict[str, bool]]:
    """Load saved records, returning an empty record set for a new install."""
    if not DATA_FILE.exists():
        return {}
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        st.warning("저장 기록을 읽지 못해 새 기록으로 시작합니다.")
    return {}


def save_records(records: dict[str, dict[str, bool]]) -> None:
    """Persist records as UTF-8 JSON beside this app."""
    DATA_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def week_start(day: date) -> date:
    """Return Monday for the week containing day."""
    return day - timedelta(days=day.weekday())


def month_shift(day: date, offset: int) -> date:
    """Move by whole months while keeping the day within the destination month."""
    month_index = day.year * 12 + day.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def render_month(records: dict[str, dict[str, bool]], month: date) -> None:
    """Render a Monday-first month grid with an icon for each completed day."""
    st.subheader("월간 실천 캘린더")
    previous_col, title_col, next_col = st.columns([1, 4, 1])
    if previous_col.button("‹ 이전 달", use_container_width=True):
        st.session_state.calendar_month = month_shift(month, -1).replace(day=1)
        st.rerun()
    title_col.markdown(
        f"<h3 style='text-align:center; margin:0.35rem 0'>{month:%Y년 %m월}</h3>",
        unsafe_allow_html=True,
    )
    if next_col.button("다음 달 ›", use_container_width=True):
        st.session_state.calendar_month = month_shift(month, 1).replace(day=1)
        st.rerun()

    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    header = st.columns(7)
    for column, weekday in zip(header, weekdays):
        column.markdown(f"<div style='text-align:center'><b>{weekday}</b></div>", unsafe_allow_html=True)

    month_grid = calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)
    for week in month_grid:
        columns = st.columns(7)
        for column, day in zip(columns, week):
            if day.month != month.month:
                column.markdown("<div style='height:3.8rem'></div>", unsafe_allow_html=True)
                continue
            day_records = records.get(day.isoformat(), {})
            completed = sum(bool(day_records.get(goal_id)) for goal_id in GOALS)
            icon = "🌸" if completed == len(GOALS) else "🌱" if completed else ""
            muted = "#888" if day > date.today() else "#222"
            column.markdown(
                f"<div style='height:3.8rem;text-align:center;border:1px solid #e8eee8;"
                f"border-radius:8px;padding:4px;color:{muted}'>"
                f"<div>{day.day}</div><div style='font-size:1.25rem'>{icon or '&nbsp;'}</div></div>",
                unsafe_allow_html=True,
            )
    st.caption("🌱 하나 이상 실천 · 🌸 세 가지 모두 실천")


def get_gemini_api_key() -> str | None:
    """Read the key from Streamlit secrets first, then environment variables."""
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    except (FileNotFoundError, KeyError):
        return os.getenv("GEMINI_API_KEY")


def analyze_recyclable(image_bytes: bytes, mime_type: str, api_key: str) -> str:
    """Ask Gemini to identify an item and explain cautious local disposal steps."""
    from google import genai
    from google.genai import types

    # Bound the wait so a stalled API call cannot leave the user spinning indefinitely.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=45_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    prompt = """사진 속 물건을 확인하고 한국에서 일반적으로 적용되는 분리배출 방법을 한국어로 안내해 주세요.
물건명과 재질을 먼저 말하고, 내용물 비우기·헹구기·라벨/뚜껑 분리 등 필요한 준비,
배출 분류와 주의사항을 짧은 항목으로 설명하세요. 사진으로 확실히 판단하기 어렵다면
추측하지 말고 불확실한 점과 사용자가 확인할 방법을 알려주세요. 분리배출 규칙은
지자체별로 다를 수 있으므로 최종 안내에서 거주지 기준 확인을 권하세요."""
    try:
        for model_index, model_name in enumerate(GEMINI_MODELS):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    ],
                )
                return response.text or "사진을 분석하지 못했습니다. 더 밝고 선명한 사진으로 다시 시도해 주세요."
            except Exception as error:
                # 503 means capacity pressure; 504 means the model exceeded its deadline.
                # Both are transient, so try the alternate model once.
                if getattr(error, "code", None) not in (503, 504) or model_index == len(GEMINI_MODELS) - 1:
                    raise
        return "사진을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요."
    finally:
        client.close()


st.set_page_config(page_title="오늘의 작은 실천", page_icon="🌱", layout="centered")
st.title("♻️ 지구를 위한 오늘의 실천")
st.caption("사진으로 분리배출 방법을 확인하고, 작은 실천도 기록해 보세요.")

recycle_tab, planner_tab = st.tabs(["♻️ 재활용 도우미", "🌱 실천 플래너"])
with recycle_tab:
    st.header("무엇을 어떻게 버릴까요?")
    st.write("사진을 촬영하거나 업로드하면 AI가 품목을 확인하고 분리배출 방법을 안내합니다.")
    input_method = st.radio("사진 가져오기", ["카메라 촬영", "사진 업로드"], horizontal=True)
    photo = None
    if input_method == "카메라 촬영":
        photo = st.camera_input("재활용할 물건을 촬영하세요", key="recycle_camera")
    else:
        photo = st.file_uploader(
            "재활용할 물건 사진을 선택하세요",
            type=["jpg", "jpeg", "png", "webp", "heic", "heif"],
            help="물건 하나가 잘 보이도록 촬영하면 더 정확하게 안내할 수 있어요.",
            key="recycle_upload",
        )

    if photo:
        st.image(photo, caption="분석할 사진", use_container_width=True)
        if st.button("분리배출 방법 확인하기", type="primary", use_container_width=True):
            api_key = get_gemini_api_key()
            if not api_key:
                st.error("Gemini API 키가 설정되지 않았습니다. README의 설정 방법을 확인해 주세요.")
            else:
                try:
                    with st.spinner("사진을 분석하고 있어요. 응답이 지연되면 다른 Gemini 모델로 다시 시도합니다..."):
                        advice = analyze_recyclable(photo.getvalue(), photo.type, api_key)
                    st.subheader("분리배출 안내")
                    st.markdown(advice)
                    st.info("분리배출 기준은 지자체와 품목 상태에 따라 다를 수 있어요. 최종 배출 전 거주지 안내도 확인해 주세요.")
                except Exception as error:
                    status_code = getattr(error, "code", None)
                    api_message = getattr(error, "message", None)
                    details = []
                    if status_code is not None:
                        details.append(f"API 상태 코드: {status_code}")
                    if api_message:
                        details.append(str(api_message)[:500])
                    detail_text = "\n\n" + "\n".join(details) if details else ""
                    st.error(
                        "사진 분석에 실패했습니다. 잠시 후 다시 시도해 주세요. "
                        f"(오류: {type(error).__name__}){detail_text}"
                    )
    st.caption("사진은 분석을 위해 Gemini API로 전송됩니다. API 키와 이미지 처리는 Gemini 서비스 정책을 따릅니다.")

with planner_tab:
    st.header("🌱 오늘의 작은 실천")
    st.caption("작은 실천을 기록하고, 이번 주와 이번 달의 변화를 확인해 보세요.")

    records = load_records()
    today = date.today()
    if "calendar_month" not in st.session_state:
        st.session_state.calendar_month = today.replace(day=1)
    today_key = today.isoformat()
    today_records = records.setdefault(today_key, {})

    st.subheader(f"오늘의 실천 · {today:%Y년 %m월 %d일}")
    changed = False
    for goal_id, label in GOALS.items():
        done = st.checkbox(label, value=bool(today_records.get(goal_id)), key=f"{today_key}_{goal_id}")
        if today_records.get(goal_id, False) != done:
            today_records[goal_id] = done
            changed = True

    if changed:
        save_records(records)

    start = week_start(today)
    week_days = [start + timedelta(days=offset) for offset in range(7)]
    weekly_counts = {
        goal_id: sum(bool(records.get(day.isoformat(), {}).get(goal_id)) for day in week_days)
        for goal_id in GOALS
    }
    total = sum(weekly_counts.values())

    st.subheader("이번 주 실천 현황")
    st.metric("총 실천 횟수", f"{total}회", help="이번 주 월요일부터 일요일까지의 체크 기록입니다.")
    for goal_id, label in GOALS.items():
        count = weekly_counts[goal_id]
        st.write(f"**{label}** · {count}회")
        st.progress(count / 7, text=f"이번 주 {count}/7일")

    render_month(records, st.session_state.calendar_month)
    st.caption("기록은 현재 실행 환경의 Src/planner_data.json 파일에 저장됩니다.")
