from functools import lru_cache
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select

from app.db.engine import Database, get_database
from app.db.models import Run, User, utcnow
from app.graph.build import build_graph
from app.graph.state import EmailMessage, initial_state
from app.runlog.logger import log_event, recording
from app.services.openai_keys import user_openai


def start_run(*, user_id: int, email: EmailMessage, mode="live", reflection_enabled=None,
              scenario=None, database: Database | None = None, graph=None, key_cipher=None):
    if mode not in {"live", "test"}:
        raise ValueError("mode는 live 또는 test여야 합니다")
    database = database or get_database()
    with database.session() as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError("등록되지 않은 사용자입니다")
        if reflection_enabled is None:
            reflection_enabled = user.reflection_enabled
    state = initial_state(
        run_id=uuid4().hex, user_id=user_id, mode=mode, email=email,
        reflection_enabled=reflection_enabled,
    )
    with database.session() as session:
        session.add(Run(
            run_id=state["run_id"], user_id=user_id, mode=mode,
            message_id=state["message_id"], thread_id=state["thread_id"],
            reflection_enabled=reflection_enabled, scenario=scenario if mode == "test" else None,
        ))
    started = perf_counter()
    with recording(database, state["run_id"]):
        log_event(state["run_id"], "run_start", detail={
            "mode": mode, "reflection_enabled": reflection_enabled,
            "message_id": state["message_id"], "thread_id": state["thread_id"],
        })
        log_event(state["run_id"], "route", node="__start__", detail={"to": "load_memory", "reason": "fixed"})
        try:
            with user_openai(database, user_id, cipher=key_cipher) as ai:
                result = (graph if graph is not None else get_graph()).invoke(
                    state, config={"recursion_limit": 64},
                )
            if ai.issue is not None:
                result.update(end_reason="failed", step_status="failed", needs_review=True,
                              notice=ai.issue.code.lower() if ai.issue.code.startswith("WORKER_") else "openai_key_required",
                              candidates=[])
            if result["end_reason"] is None:
                result["end_reason"] = "ignored" if result["intent"] == "ignore" else "failed"
        except Exception as error:
            # 엔진 차원의 오류도 실행 종료와 함께 남긴다. 원문은 저장하지 않는다.
            result = {**state, "end_reason": "failed", "step_status": "failed"}
            log_event(state["run_id"], "error", detail={
                "kind": "internal", "message": f"그래프 실행 실패 ({type(error).__name__})",
            })
        duration = int((perf_counter() - started) * 1000)
        with database.session() as session:
            run = session.scalar(select(Run).where(Run.run_id == state["run_id"], Run.user_id == user_id))
            run.ended_at = utcnow()
            run.end_reason = result["end_reason"]
            run.duration_ms = duration
        log_event(state["run_id"], "run_end", duration_ms=duration, detail={
            "end_reason": result["end_reason"], "call_retries": result["call_retries"],
            "reflection_retries": result["reflection_retries"], "duration_ms": duration,
        })
    return result


@lru_cache(maxsize=1)
def get_graph():
    return build_graph()
