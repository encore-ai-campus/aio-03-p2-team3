from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

from sqlalchemy import func, select

from app.db.engine import Database, get_database
from app.db.models import RunEvent, utcnow

_database: ContextVar[Database | None] = ContextVar("run_database", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_node: ContextVar[str | None] = ContextVar("node", default=None)


@contextmanager
def recording(database: Database, run_id: str):
    db_token = _database.set(database)
    run_token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(run_token)
        _database.reset(db_token)


def current_database() -> Database:
    """지금 실행 중인 그래프가 기록하는 DB. 실행 밖에서는 기본 DB를 돌려준다."""
    return _database.get() or get_database()


def log_event(run_id: str, event: str, *, node: str | None = None,
              tool: str | None = None, detail: dict | None = None,
              duration_ms: int | None = None, database: Database | None = None):
    database = database or _database.get() or get_database()
    with database.session() as session:
        seq = session.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
        session.add(RunEvent(
            run_id=run_id, seq=0 if seq is None else seq + 1,
            event=event, node=node, tool=tool, detail=detail or {}, duration_ms=duration_ms,
        ))


def current_database() -> Database:
    """실행 중인 그래프가 쓰는 DB(시험은 메모리 DB). 실행 밖이면 기본 DB."""
    return _database.get() or get_database()


def current_event(event: str, **kwargs):
    run_id = _run_id.get()
    if run_id is not None:
        kwargs.setdefault("node", _node.get())
        log_event(run_id, event, **kwargs)


def current_run_id() -> str | None:
    """큐 작업도 현재 메일 실행의 추적 ID를 사용한다. 독립 추출은 별도 UUID를 만든다."""
    return _run_id.get()


def traced_node(name: str):
    def decorate(function):
        @wraps(function)
        def traced(state):
            token = _node.set(name)
            started = perf_counter()
            current_event("node_start")
            try:
                update = function(state)
            except Exception as error:
                # 예외 문자열에는 API 키·메일 본문이 섞일 수 있으므로 저장하지 않는다.
                message = f"노드 실행 실패 ({type(error).__name__})"
                current_event("error", detail={"kind": "internal", "message": message})
                update = {"step_status": "failed", "errors": [{
                    "node": name, "kind": "internal", "message": message,
                    "at": utcnow().isoformat(),
                }]}
            try:
                current_event("node_end", duration_ms=int((perf_counter() - started) * 1000), detail={
                    "step_status": update.get("step_status", state["step_status"]),
                    "changed_fields": sorted(update),
                })
                destination = {
                    "load_memory": "analyze_email", "save_pending": "__end__", "finish_failed": "__end__",
                }.get(name)
                if destination:
                    current_event("route", detail={"to": destination, "reason": "fixed"})
                return update
            finally:
                _node.reset(token)
        return traced
    return decorate


def traced_route(name: str, route):
    def choose(state):
        destination = route(state)
        reflection = state["reflection"]
        log_event(state["run_id"], "route", node=name, detail={
            "to": destination,
            "reason": {
                "step_status": state["step_status"], "intent": state["intent"],
                "missing_fields": state["missing_fields"],
                "reflection_enabled": state["reflection_enabled"],
                "retry_target": reflection["retry_target"] if reflection else None,
            },
        })
        return destination
    return choose
