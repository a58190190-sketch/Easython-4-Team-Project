"""Tkinter desktop UI and orchestration of Easython workflows."""
from __future__ import annotations
import json
import math
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from .config import *
from .guidance import *
from .provider import *
from .server import start_server
from .flow import apply_response, status_guide
from .schema import extract_json_object, validate_guidance
from .session import MAX_QUESTIONS, current_goal, current_session, start_session, stop_session
from .vision import analyze_capture

def main() -> None:
    checker = (Path(__file__).resolve().parent.parent / "check_requirements.py")
    check = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check.returncode:
        notice = tk.Tk()
        notice.withdraw()
        message = (check.stdout + check.stderr).strip() or "requirements.txt 확인 중 오류가 발생했습니다."
        messagebox.showerror("필수 라이브러리 확인 실패", f"{message}\n\ninstall.bat을 실행한 뒤 다시 시작하세요.", parent=notice)
        notice.destroy()
        return
    global cv2, np
    import cv2
    import numpy as np

    root = tk.Tk()
    root.title("Easython - 가이드 및 설정")
    root.geometry("760x640")
    root.minsize(620, 500)
    try:
        start_server()
    except OSError as exc:
        messagebox.showerror("서버 시작 실패", f"로컬 서버 포트 {PORT}를 사용할 수 없습니다.\n{exc}")
        root.destroy()
        return

    tk.Label(root, text="Easython", font=("Malgun Gothic", 20, "bold")).pack(pady=(16, 3))
    tk.Label(root, text="웹사이트 UI 분석 및 이용 경로 찾기", font=("Malgun Gothic", 10)).pack()
    status = tk.Label(root, text="확장 프로그램 미연결 · Chrome 페이지를 새로고침하세요", fg="#b45309")
    status.pack(pady=9)
    page_label = tk.Label(root, text="분석할 페이지를 확장 프로그램에서 전송하세요.", wraplength=510, justify="left")
    page_label.pack(fill="x", padx=22, pady=10)
    screen_status = tk.Label(root, text="화면을 수신하면 OpenCV로 현재 화면의 UI 후보 영역을 분석합니다.", wraplength=700, justify="left", fg="#555", font=("Malgun Gothic", 9))
    screen_status.pack(fill="x", padx=20, pady=(0, 4))
    provider_var = tk.StringVar(value=DEFAULT_PROVIDER)
    model_var = tk.StringVar(value=PROVIDER_CONFIG[DEFAULT_PROVIDER]["default_model"])
    model_row = tk.Frame(root)
    model_row.pack(fill="x", padx=20, pady=(2, 5))
    tk.Label(model_row, text="AI 제공자:").pack(side="left")
    provider_combo = ttk.Combobox(model_row, textvariable=provider_var, values=tuple(PROVIDER_CONFIG), state="readonly", width=14)
    provider_combo.pack(side="left", padx=(6, 12))
    tk.Label(model_row, text="모델:").pack(side="left")
    model_entry = tk.Entry(model_row, textvariable=model_var, width=23)
    model_entry.pack(side="left", padx=6)
    api_status = tk.Label(root, text="AI API 키 확인 중…", fg="#555", font=("Malgun Gothic", 9))
    api_status.pack(pady=4)
    controls = tk.Frame(root)
    controls.pack(pady=5)
    stop_button = tk.Button(controls, text="안내 종료", command=lambda: stop_guidance(), state="disabled", padx=12, pady=7)
    stop_button.pack(side="left", padx=5)
    replay_button = tk.Button(controls, text="접근성 확인 다시보기", command=lambda: replay_guidance(), state="disabled", padx=12, pady=7)
    replay_button.pack(side="left", padx=5)
    api_key_button = tk.Button(controls, text="API 키 설정", command=lambda: configure_api_key(), font=("Malgun Gothic", 10), padx=12, pady=7)
    api_key_button.pack(side="left", padx=5)
    guide_instruction_label = tk.Label(root, text="검색어와 안내 내용은 이 창에 표시됩니다.", anchor="w", justify="left", wraplength=700, fg="#FF0000", font=("Malgun Gothic", 10, "bold"))
    guide_instruction_label.pack(fill="x", padx=20, pady=(0, 3))
    analysis_status_label = tk.Label(root, text="Chrome에서 현재 탭을 전송한 뒤 기능을 입력하세요. 입력 내용은 유지됩니다.", anchor="w", justify="left", wraplength=700, fg="#555", font=("Malgun Gothic", 9))
    analysis_status_label.pack(fill="x", padx=20, pady=3)
    progress_row = tk.Frame(root)
    progress_row.pack(fill="x", padx=20, pady=(0, 4))
    analysis_progress_label = tk.Label(progress_row, text="분석 대기 · 0%", anchor="w", fg="#FF0000", font=("Malgun Gothic", 9, "bold"))
    analysis_progress_label.pack(fill="x")
    analysis_progress_bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0)
    analysis_progress_bar.pack(fill="x", pady=(2, 0))
    transcript: scrolledtext.ScrolledText = scrolledtext.ScrolledText(root, wrap="word", state="disabled", font=("Malgun Gothic", 10), height=12)
    transcript.pack(fill="both", expand=True, padx=20, pady=8)
    tk.Label(root, text="원하는 기능은 Chrome 확장 프로그램 팝업에서 입력하세요. 선택한 AI 제공자 API로 목표와 페이지 UI 정보가 전송됩니다.", wraplength=700, fg="#666", font=("Malgun Gothic", 9)).pack(padx=18, pady=(0, 10))
    current_page: dict[str, Any] | None = None
    history: list[dict[str, str]] = []
    active_goal: str | None = None
    last_goal: str | None = None
    guide_active = False
    analysis_busy = False
    capture_revision = 0
    analyzed_sites: set[str] = set()
    analysis_progress = 0.0
    analysis_started_at = 0.0
    analysis_phase = "요청 준비"
    analysis_dot_index = 0
    analysis_animation_job: str | None = None

    previous_provider = {"name": DEFAULT_PROVIDER}

    def refresh_api_status() -> None:
        provider = provider_var.get()
        try:
            configured = bool(get_provider_api_key(provider))
        except RuntimeError:
            configured = False
        api_status.config(text=f"{provider} API 키 등록됨" if configured else f"{provider} API 키 미등록", fg="#15803d" if configured else "#b45309")
        api_key_button.config(text=f"{provider} API 키 설정")

    def provider_changed(event: Any = None) -> None:
        old_provider = previous_provider["name"]
        new_provider = provider_var.get()
        old_default = PROVIDER_CONFIG[old_provider]["default_model"]
        if not model_var.get().strip() or model_var.get().strip() == old_default:
            model_var.set(PROVIDER_CONFIG[new_provider]["default_model"])
        previous_provider["name"] = new_provider
        refresh_api_status()

    provider_combo.bind("<<ComboboxSelected>>", provider_changed)

    def configure_api_key(required: bool = False) -> bool:
        try:
            import keyring
        except ImportError:
            messagebox.showerror("필수 라이브러리 없음", "install.bat을 실행해 필수 라이브러리를 설치하세요.", parent=root)
            return False
        dialog = tk.Toplevel(root)
        selected_provider = provider_var.get()
        config = PROVIDER_CONFIG[selected_provider]
        dialog.title(f"{selected_provider} API 키 설정")
        dialog.geometry("500x300")
        dialog.resizable(False, False)
        dialog.transient(root)
        if required:
            dialog.grab_set()
            dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        tk.Label(dialog, text=f"{selected_provider} API 키 등록", font=("Malgun Gothic", 14, "bold")).pack(pady=(15, 3))
        tk.Label(dialog, text="키는 Windows 자격 증명 저장소에 보관됩니다.", font=("Malgun Gothic", 9)).pack(pady=(0, 8))
        key_entry = tk.Entry(dialog, show="●", width=58)
        key_entry.pack(padx=18, fill="x")
        try:
            saved = keyring.get_password(KEYRING_SERVICE, config["key_user"])
            if saved:
                key_entry.insert(0, saved)
        except Exception:
            pass
        tk.Button(dialog, text=f"{selected_provider} API 키 발급 페이지 열기", command=lambda: webbrowser.open(config["key_url"]), fg="#1d4ed8").pack(pady=(7, 0))
        status_label = tk.Label(dialog, text="키 검증을 위해 짧은 API 요청 1회를 보냅니다. 제공자 계정의 한도나 요금이 적용될 수 있습니다.", fg="#555", wraplength=460)
        status_label.pack(pady=9)
        result = {"saved": False}
        check_events: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def finish(error: str | None) -> None:
            if error:
                status_label.config(text=error, fg="#b91c1c")
                save_button.config(state="normal", text="확인 후 저장")
                return
            result["saved"] = True
            refresh_api_status()
            status_label.config(text="키 확인 및 보안 저장 완료.", fg="#15803d")
            dialog.after(700, dialog.destroy)

        def check_and_save() -> None:
            key = key_entry.get().strip()
            if not key:
                status_label.config(text="API 키를 입력해 주세요.", fg="#b91c1c")
                return
            selected_model = model_var.get().strip() or DEFAULT_MODEL
            save_button.config(state="disabled", text="확인 중…")
            status_label.config(text=f"{selected_provider} 연결 확인 중 · 서버 응답 제한 20초", fg="#555")

            def worker() -> None:
                try:
                    verify_provider_api_key(selected_provider, key, selected_model, on_status=lambda text: check_events.put(("progress", text)))
                    keyring.set_password(KEYRING_SERVICE, config["key_user"], key)
                    check_events.put(("result", None))
                except Exception as exc:
                    check_events.put(("result", str(exc)))

            def poll_result() -> None:
                try:
                    kind, value = check_events.get_nowait()
                    if kind == "progress" and value:
                        status_label.config(text=value, fg="#555")
                        dialog.after(100, poll_result)
                    else:
                        finish(value)
                except queue.Empty:
                    if dialog.winfo_exists():
                        dialog.after(100, poll_result)

            threading.Thread(target=worker, daemon=True).start()
            dialog.after(100, poll_result)

        save_button = tk.Button(dialog, text="확인 후 저장", command=check_and_save, bg="#2563eb", fg="white", padx=14, pady=5)
        save_button.pack()
        tk.Button(dialog, text="취소" if not required else "앱 종료", command=dialog.destroy).pack(pady=(6, 0))
        dialog.wait_window()
        refresh_api_status()
        return result["saved"]

    def append_chat(who: str, content: str) -> None:
        transcript.configure(state="normal")
        transcript.insert("end", f"{who}: {content}\n\n")
        transcript.see("end")
        transcript.configure(state="disabled")

    def publish_analysis_status(indeterminate: bool = False, phase: str | None = None) -> None:
        with state_lock:
            state["analysis_status"] = {
                "busy": analysis_busy,
                "progress": max(0, min(100, int(analysis_progress))),
                "phase": phase or (analysis_phase if analysis_busy else ("분석 완료" if analysis_progress >= 100 else "분석 대기")),
                "indeterminate": bool(analysis_busy and indeterminate),
            }

    def refresh_analysis_progress() -> None:
        nonlocal analysis_progress, analysis_dot_index, analysis_animation_job
        if not analysis_busy:
            publish_analysis_status()
            analysis_animation_job = None
            return
        elapsed = max(0.0, time.monotonic() - analysis_started_at)
        estimated = min(92.0, 5.0 + 87.0 * (1.0 - math.exp(-elapsed / 30.0)))
        analysis_progress = max(analysis_progress, estimated)
        analysis_progress_bar.configure(value=analysis_progress)
        dots = "." * (analysis_dot_index % 4)
        analysis_progress_label.config(text=f"분석중{dots} · 예상 진행률 {int(analysis_progress)}% · {analysis_phase}")
        publish_analysis_status("분석 요청 중" in analysis_phase)
        analysis_dot_index += 1
        analysis_animation_job = root.after(300, refresh_analysis_progress)

    def start_goal(goal: str) -> None:
        nonlocal active_goal, last_goal, guide_active, history
        goal = goal.strip()[:1200]
        if not goal or not current_page:
            return
        is_new_goal = goal != active_goal or not guide_active
        try:
            has_key = bool(get_provider_api_key(provider_var.get()))
        except RuntimeError:
            has_key = False
        if not has_key and not configure_api_key():
            analysis_status_label.config(text="API 키를 등록한 뒤 확장 프로그램에서 현재 화면을 다시 보내세요.", fg="#b91c1c")
            return
        # A session reopened from the page ("아직 안 끝났어요") keeps its progress.
        if is_new_goal and current_goal() != goal:
            history = []
            start_session(goal)
        last_goal = goal
        active_goal = goal
        append_chat("나", goal)
        with state_lock:
            state["accessibility_check"] = False
            state["guide"] = None
            state["display"] = None
        guide_instruction_label.config(text="1차 후보 탐색 중 · 접근 가능성은 아직 확인하지 않습니다.")
        guide_active = True
        stop_button.configure(state="normal")
        replay_button.configure(state="disabled")
        replay_button.configure(text="접근성 확인 다시보기")
        if analysis_busy:
            analysis_status_label.config(text="새 기능을 받았습니다. 현재 요청이 끝나면 이어서 분석합니다.", fg="#2563eb")
        else:
            analyze_goal(goal)

    def replay_guidance() -> None:
        nonlocal active_goal, guide_active, history
        if not last_goal or not current_page or analysis_busy:
            return
        active_goal = last_goal
        guide_active = True
        # Replay restarts the goal from the current screen with fresh progress.
        start_session(active_goal)
        history = []
        with state_lock:
            state["accessibility_check"] = True
        append_chat("안내", "접근성 확인 다시보기: 클릭·hover 도달 가능성을 적용해 현재 화면부터 다시 분석합니다.")
        guide_instruction_label.config(text="2차 접근성 확인 중 · 실제 클릭 또는 hover 도달 가능성을 검사합니다.")
        analysis_status_label.config(text="접근 가능한 UI를 확인하며 다시 분석합니다.", fg="#555")
        stop_button.configure(state="normal")
        replay_button.configure(state="disabled")
        replay_button.configure(text="다시보기")
        with state_lock:
            state["guide"] = None
            state["display"] = None
            state["planned_route"] = ""
            state["route_position"] = ""
        analyze_goal(active_goal)

    def analyze_goal(goal: str) -> None:
        nonlocal analysis_busy, analysis_progress, analysis_started_at, analysis_phase, analysis_dot_index, analysis_animation_job
        if not current_page or analysis_busy:
            return
        site_key = page_site_key(current_page.get("url", ""))
        screen_only = site_key in analyzed_sites and not bool(current_page.get("html_fallback", False))
        conversation = history.copy()
        conversation.append({"role": "user", "content": goal})
        history.append({"role": "user", "content": goal})
        analysis_busy = True
        analysis_progress = 5.0
        analysis_started_at = time.monotonic()
        analysis_phase = "현재 화면만 분석 중" if screen_only else "사이트 구조 확인 중"
        publish_analysis_status()
        analysis_dot_index = 0
        analysis_progress_bar.configure(value=analysis_progress)
        analysis_progress_label.config(text=f"예상 진행률 {int(analysis_progress)}% · {analysis_phase}")
        guide_instruction_label.config(text="같은 사이트의 앞선 분석을 바탕으로 현재 화면만 확인합니다." if screen_only else "사이트와 현재 화면에서 목표에 맞는 UI를 찾고 있습니다.")
        if analysis_animation_job:
            root.after_cancel(analysis_animation_job)
        analysis_animation_job = root.after(300, refresh_analysis_progress)
        page_snapshot = current_page.copy()
        revision_snapshot = capture_revision
        selected_model = model_var.get().strip()
        selected_provider = provider_var.get()
        with state_lock:
            accessibility_check = bool(state.get("accessibility_check", False))
        analysis_status_label.config(text="현재 화면 요소만 분석 중…" if screen_only else "현재 페이지 규모와 예상 요청량 계산 중…", fg="#555")

        session = current_session()
        session_context = session.prompt_context() if session else None
        questions_asked = session.questions_asked if session else MAX_QUESTIONS

        def work() -> None:
            structured = None
            answer = ""
            try:
                correction = ""
                # One corrective retry when the reply is not usable JSON for this screen.
                for _attempt in range(2):
                    answer = call_nim(
                        page_snapshot, goal, conversation, selected_model, provider=selected_provider,
                        on_status=lambda text: ui_events.put(("analysis_status", text)),
                        screen_only=screen_only,
                        accessibility_check=accessibility_check,
                        session_context=session_context,
                        correction=correction,
                    )
                    structured = validate_guidance(
                        extract_json_object(answer), page_snapshot.get("elements", []),
                        questions_asked=questions_asked, max_questions=MAX_QUESTIONS,
                    )
                    if structured:
                        break
                    correction = ("직전 응답을 사용할 수 없었다. 설명 없이 JSON 객체 하나만 다시 출력하고, "
                                  "target_id는 visible_elements에 실제로 있는 id만 쓴다.")
            except Exception as exc:
                answer = f"분석 오류: {exc}"
            ui_events.put(("answer", (goal, answer, page_snapshot, revision_snapshot, site_key, screen_only, structured)))
        threading.Thread(target=work, daemon=True).start()

    def set_active_page(page: dict[str, Any], requested_goal: str = "") -> None:
        nonlocal current_page, history, capture_revision, analysis_progress
        requested_goal = requested_goal.strip()[:1200]
        continuing = guide_active and active_goal is not None and (not requested_goal or requested_goal == active_goal)
        capture_revision += 1
        current_page = page
        visible_ui_count = sum(bool(element.get("in_view", False)) for element in page.get("elements", []))
        page_label.config(text=f"페이지 정보 수신\n{page['url']}\n현재 화면 UI 요소 {visible_ui_count}개 수신")
        if continuing:
            current_screen = str(page.get("title") or "현재 화면")
            with state_lock:
                current_route = str(state.get("planned_route", ""))
                if current_route:
                    state["route_position"] = current_screen
            if current_route:
                guide_instruction_label.config(text=f"접근 경로: {current_route}\n현재 위치: {current_screen} 화면을 분석하고 있습니다.")
        viewport = page.get("viewport", {})
        vision = page.get("vision", {})
        screen_text = f"OpenCV {vision.get('width', 0)}×{vision.get('height', 0)} · 화면 후보 영역 {vision.get('region_count', 0)}개 · UI 요소 {visible_ui_count}개"
        screen_status.config(text=screen_text + "\n분석 후 현재 화면에 표시할 안내 UI가 없을 때만 화면 이동을 권고합니다.", fg="#555")
        transcript.configure(state="normal")
        if not continuing:
            history = []
            transcript.delete("1.0", "end")
            transcript.configure(state="disabled")
            analysis_progress = 0.0
            analysis_progress_bar.configure(value=0)
            analysis_progress_label.config(text="분석 대기 · 0%")
            guide_instruction_label.config(text="화면을 분석하면 안내 내용과 입력할 검색어를 여기에 표시합니다.")
        if continuing:
            analysis_status_label.config(text="새 화면을 받았습니다. 기존 목표에 맞게 분석합니다.", fg="#2563eb")
            append_chat("화면", "새 화면을 수신했습니다. 기존 목표에 맞게 분석합니다.")
            if not analysis_busy:
                root.after(100, lambda: analyze_goal(active_goal or ""))
            elif requested_goal and requested_goal != active_goal:
                start_goal(requested_goal)
        elif requested_goal:
            start_goal(requested_goal)
        else:
            analysis_status_label.config(text="Chrome 확장 프로그램 팝업에서 기능을 입력해 현재 화면을 보내세요.", fg="#15803d")
            append_chat("안내", "확장 프로그램에서 입력한 기능을 분석합니다. 프로그램은 자동으로 클릭하지 않습니다.")

    def stop_guidance() -> None:
        nonlocal guide_active, active_goal
        guide_active = False
        active_goal = None
        stop_session()
        with state_lock:
            state["guide"] = None
            state["display"] = None
        stop_button.configure(state="disabled")
        guide_instruction_label.config(text="화면 안내를 종료했습니다.")
        analysis_status_label.config(text="화면 안내를 종료했습니다.", fg="#555")
        replay_button.configure(state="normal" if last_goal and current_page and not analysis_busy else "disabled")

    def describe_guide(guide: dict[str, Any]) -> str:
        """One line for the desktop transcript; the page shows the same sentence."""
        status_name = {"next": "안내", "user_input": "직접 입력", "ask": "질문", "blocked": "잠시 멈춤", "done": "완료"}
        text = f"[{status_name.get(guide.get('status'), '안내')}] {guide.get('say', '')}"
        if guide.get("status") == "ask":
            text += " · 선택지: " + ", ".join(option["label"] for option in guide.get("options", []))
        if guide.get("input_hint"):
            text += f" · {guide['input_hint']}"
        if guide.get("risk"):
            text += " · 중요한 단계(결과가 생기는 버튼)"
        return text

    def finish_goal() -> None:
        """The AI judged the goal reached; flow.apply_response already ended the session."""
        nonlocal guide_active, active_goal
        guide_active = False
        active_goal = None
        stop_button.configure(state="disabled")
        replay_button.configure(state="normal" if last_goal and current_page else "disabled")
        analysis_status_label.config(text="목표를 달성해 안내를 마쳤습니다.", fg="#15803d")

    def pump_events() -> None:
        nonlocal analysis_busy, analysis_progress, analysis_phase, analysis_animation_job, guide_active, active_goal, last_goal
        try:
            while True:
                kind, value = ui_events.get_nowait()
                if kind == "capture":
                    page, goal = value
                    set_active_page(page, goal)
                elif kind == "guide_note":
                    append_chat("화면 가이드", str(value))
                    guide_instruction_label.config(text=str(value))
                elif kind == "reopen":
                    # "아직 안 끝났어요" on the page: resume; the extension sends a fresh capture.
                    if value:
                        active_goal = last_goal = str(value)
                        guide_active = True
                        stop_button.configure(state="normal")
                        append_chat("안내", "아직 끝나지 않았다는 답을 받아 이어서 안내합니다.")
                elif kind == "answer":
                    goal, answer, page_snapshot, revision_snapshot, site_key, screen_only, structured = value
                    analysis_busy = False
                    if analysis_animation_job:
                        root.after_cancel(analysis_animation_job)
                        analysis_animation_job = None
                    analysis_progress = 100.0
                    analysis_progress_bar.configure(value=100)
                    request_failed = answer.startswith("분석 오류:")
                    publish_analysis_status(phase="분석 오류" if request_failed else "분석 완료")
                    if not request_failed:
                        analyzed_sites.add(site_key)
                        with state_lock:
                            state["analyzed_sites"].add(site_key)
                    analysis_progress_label.config(text="분석 종료 · 100% · 오류" if request_failed else "분석 완료 · 100%")
                    if revision_snapshot == capture_revision:
                        history.append({"role": "assistant", "content": answer})
                    if request_failed:
                        append_chat("안내", answer)
                    guide_note = ""
                    is_current = guide_active and revision_snapshot == capture_revision
                    if is_current and structured:
                        shown = apply_response(page_snapshot, structured, goal)
                        guide_note = describe_guide(shown)
                        if shown["status"] == "done":
                            finish_goal()
                    elif is_current:
                        status_guide(
                            str(page_snapshot.get("url", "")), "blocked",
                            "안내를 불러오지 못했어요. 잠시 뒤 ‘다시 안내’를 눌러 주세요." if request_failed
                            else "다음 안내를 찾지 못했어요. ‘다시 안내’를 눌러 주세요.",
                            goal,
                        )
                        if not request_failed:
                            append_chat("AI 응답(해석 실패)", answer[:600])
                    if guide_note:
                        append_chat("화면 가이드", guide_note)
                        guide_instruction_label.config(text=guide_note)
                    elif request_failed:
                        guide_instruction_label.config(text="분석에 실패했습니다. API 키와 연결 상태를 확인한 뒤 다시 시도하세요.")
                    if revision_snapshot == capture_revision and guide_active:
                        viewport = page_snapshot.get("viewport", {})
                        visible_ui_count = sum(bool(element.get("in_view", False)) for element in page_snapshot.get("elements", []))
                        vision = page_snapshot.get("vision", {})
                        screen_text = f"OpenCV {vision.get('width', 0)}×{vision.get('height', 0)} · 화면 후보 영역 {vision.get('region_count', 0)}개 · UI 요소 {visible_ui_count}개"
                        if request_failed:
                            screen_status.config(text=screen_text + "\n요청 오류로 UI 판단을 완료하지 못했습니다. 오류 내용을 확인한 뒤 다시 시도하세요.", fg="#555")
                        elif any(bool(element.get("in_view")) and (bool(element.get("actionable")) or bool(element.get("hover_actionable"))) for element in page_snapshot.get("elements", [])):
                            screen_status.config(text=screen_text + "\n현재 화면에 조작 가능한 UI가 있어 스크롤·창 크기 조정 권고를 표시하지 않습니다.", fg="#555")
                        else:
                            advice = page_snapshot.get("display_advice", "")
                            message = f"권고: {advice}" if advice else "현재 화면에서 안내할 UI를 찾지 못했습니다. 필요한 UI가 있는 영역을 확인해 주세요."
                            screen_status.config(text=screen_text + f"\n{message}", fg="#FF0000" if advice else "#555")
                    analysis_status_label.config(text=guide_note or "분석이 완료되었습니다. 안내된 동작을 하면 다음 화면을 자동으로 분석합니다.", fg="#15803d")
                    if not guide_active:
                        analysis_status_label.config(text="목표를 달성해 안내를 마쳤습니다." if structured and structured.get("status") == "done" else "화면 안내를 종료했습니다.", fg="#555")
                    if revision_snapshot != capture_revision and guide_active and active_goal:
                        root.after(100, lambda: analyze_goal(active_goal or ""))
                    else:
                        with state_lock:
                            accessibility_check = bool(state.get("accessibility_check", False))
                        replay_button.configure(
                            state="normal" if last_goal and current_page else "disabled",
                            text="다시보기" if accessibility_check else "접근성 확인 다시보기",
                        )
                elif kind == "analysis_status":
                    status_text = str(value)
                    if "페이지 규모" in status_text:
                        analysis_phase = "페이지 규모 계산 완료"
                        analysis_progress = max(analysis_progress, 20.0)
                    elif "요청 속도 조절 대기" in status_text:
                        analysis_phase = status_text
                        analysis_progress = max(analysis_progress, 25.0)
                    elif "분석 요청 중" in status_text:
                        analysis_phase = status_text
                        analysis_progress = max(analysis_progress, 38.0)
                    elif "요청 한도" in status_text:
                        analysis_phase = status_text
                        analysis_progress = max(analysis_progress, 45.0)
                    publish_analysis_status("분석 요청 중" in analysis_phase)
                    analysis_status_label.config(text=status_text, fg="#555")
        except queue.Empty:
            pass
        with state_lock:
            connected = state["last_seen"] > 0 and time.time() - state["last_seen"] < 15
        status.config(text="확장 프로그램 연결됨" if connected else "확장 프로그램 미연결 · 대상 페이지에서 확장 아이콘을 눌러 전송", fg="#15803d" if connected else "#b45309")
        root.after(250, pump_events)

    tk.Label(root, text="페이지 규모에 맞춰 앱 내부 요청 속도를 조절합니다(분당 최대 6회·추정 토큰 20,000개). 선택한 제공자의 계정 한도는 다를 수 있으며, 429 응답은 대기 후 재시도합니다.", wraplength=560, fg="#666", font=("Malgun Gothic", 9)).pack(padx=15)
    refresh_api_status()
    pump_events()
    root.mainloop()
