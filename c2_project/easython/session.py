"""Guide session: one user goal followed across pages and tabs until it ends.

The session replaces the single-string `planned_route` as the source of truth for
"what is the user trying to do and how far have they got". The HTTP server and
the desktop UI both read it, so every helper takes `state_lock` itself
(`state_lock` is re-entrant, so callers that already hold it are safe).
"""
from __future__ import annotations
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from .config import state, state_lock

# Session lifecycle. "done"/"blocked" are set from the AI response in step 2.
ACTIVE, DONE, BLOCKED, STOPPED = "active", "done", "blocked", "stopped"
# Guard rails so a confused model cannot loop forever or nag the user.
MAX_STEPS = 15
MAX_QUESTIONS = 3


@dataclass
class GuideStep:
    """One guided action on one screen."""
    url: str
    title: str
    action: str = ""
    target_id: str = ""
    target_label: str = ""
    at: float = field(default_factory=time.time)


@dataclass
class GuideSession:
    goal: str
    status: str = ACTIVE
    started_at: float = field(default_factory=time.time)
    steps: list[GuideStep] = field(default_factory=list)
    # Choices the user already made (e.g. {"로그인 방식": "간편인증"}); never raw personal data.
    answers: dict[str, str] = field(default_factory=dict)
    questions_asked: int = 0
    # How the AI will recognise the goal is reached (e.g. "로그아웃 버튼이 보임").
    completion_hint: str = ""

    def prompt_context(self) -> dict[str, Any]:
        """Compact, model-facing summary of progress so far."""
        return {
            "goal": self.goal,
            "completed_steps": [
                {"screen": step.title or step.url, "action": step.action or step.target_label}
                for step in self.steps[-8:]
            ],
            "answers": dict(self.answers),
            "questions_left": max(0, MAX_QUESTIONS - self.questions_asked),
            "completion_hint": self.completion_hint,
        }


def start_session(goal: str) -> GuideSession:
    session = GuideSession(goal=goal.strip()[:1200])
    with state_lock:
        state["session"] = session
        state["last_session"] = None
        state["step_signature"] = ""
        state["planned_route"] = ""
        state["route_position"] = ""
    return session


def stop_session(status: str = STOPPED) -> None:
    with state_lock:
        session = state.get("session")
        if isinstance(session, GuideSession):
            session.status = status
            # Kept so "아직 안 끝났어요" can resume it (flow.reopen_session).
            state["last_session"] = session
        state["session"] = None


def current_session() -> GuideSession | None:
    with state_lock:
        session = state.get("session")
        return session if isinstance(session, GuideSession) and session.status == ACTIVE else None


def is_session_active() -> bool:
    return current_session() is not None


def current_goal() -> str:
    session = current_session()
    return session.goal if session else ""


def record_step(url: str, title: str, *, action: str = "", target_id: str = "", target_label: str = "") -> bool:
    """Append a guided step. Returns False once MAX_STEPS is reached."""
    with state_lock:
        session = current_session()
        if not session:
            return False
        last = session.steps[-1] if session.steps else None
        # Re-guiding the same target on the same page is not progress.
        if last and last.url == url and last.target_id == target_id and last.target_label == target_label:
            return len(session.steps) < MAX_STEPS
        session.steps.append(GuideStep(url=url[:500], title=title[:200], action=action[:240],
                                       target_id=target_id[:40], target_label=target_label[:100]))
        return len(session.steps) < MAX_STEPS


def session_snapshot() -> dict[str, Any] | None:
    session = current_session()
    return asdict(session) if session else None
