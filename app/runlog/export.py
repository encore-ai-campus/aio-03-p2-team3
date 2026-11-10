"""실행 하나를 파일로 내보내기 — `docs/CONTRACT.md` 8.2절.

첫 줄은 `{"type": "run", …runs 열}`, 그 뒤는 `{"type": "event", …run_events 열}`을 `seq` 순서로 둔다.
모든 줄은 한 `Masker`로 가린다(8.3절). 본인 실행만 읽는다(7절: 모든 조회는 `user_id`로 거른다).
"""
import json
import re
from datetime import datetime

from sqlalchemy import select

from app.db.engine import Database
from app.db.models import Run, RunEvent
from app.runlog.mask import Masker

RUN_COLUMNS = ("run_id", "user_id", "mode", "message_id", "thread_id", "reflection_enabled",
               "started_at", "ended_at", "end_reason", "duration_ms", "scenario")
# `id`(DB 줄 번호)는 DB 밖에서 뜻이 없어 빼고, 순서는 `seq`로 본다.
EVENT_COLUMNS = ("run_id", "seq", "at", "event", "node", "tool", "detail", "duration_ms")


def _plain(value):
    return value.isoformat() if isinstance(value, datetime) else value


def load_run(database: Database, user_id: int, run_id: str) -> tuple[Run, list[RunEvent]] | None:
    """본인 실행과 그 기록 줄을 `seq` 순서로 돌려준다. 남의 실행이거나 없으면 None."""
    with database.session() as session:
        run = session.scalar(select(Run).where(Run.run_id == run_id, Run.user_id == user_id))
        if run is None:
            return None
        events = list(session.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ))
    return run, events


def list_runs(database: Database, user_id: int, limit: int = 50) -> list[Run]:
    with database.session() as session:
        return list(session.scalars(
            select(Run).where(Run.user_id == user_id).order_by(Run.started_at.desc()).limit(limit)
        ))


def run_records(run: Run, events: list[RunEvent], masker: Masker | None = None) -> list[dict]:
    """가린 줄 목록. 화면과 내보내기 파일이 같은 내용을 쓴다."""
    masker = masker or Masker(run.mode)
    rows = [{"type": "run", **{c: _plain(getattr(run, c)) for c in RUN_COLUMNS}}]
    rows += [{"type": "event", **{c: _plain(getattr(e, c)) for c in EVENT_COLUMNS}}
             for e in sorted(events, key=lambda e: e.seq)]
    masker.learn(rows)
    return [masker.value(row) for row in rows]


def export_filename(run: Run) -> str:
    """`<YYYYMMDD-HHMM>_<scenario 또는 live>_<refl-on|refl-off>_<run_id 앞 8자>.jsonl` (시각은 UTC)."""
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", run.scenario or run.mode).strip("-") or run.mode
    reflection = "refl-on" if run.reflection_enabled else "refl-off"
    return f"{run.started_at:%Y%m%d-%H%M}_{label}_{reflection}_{run.run_id[:8]}.jsonl"


def export_jsonl(database: Database, user_id: int, run_id: str) -> tuple[str, str] | None:
    """(파일 이름, 파일 내용)을 돌려준다. 남의 실행이거나 없으면 None."""
    loaded = load_run(database, user_id, run_id)
    if loaded is None:
        return None
    run, events = loaded
    lines = [json.dumps(row, ensure_ascii=False) for row in run_records(run, events)]
    return export_filename(run), "\n".join(lines) + "\n"
