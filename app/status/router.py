"""작업현황 화면의 Bearer 전용 읽기 API. 그래프·AI를 다시 실행하지 않고 기록만 읽는다(계획 17절).

작업 단위는 소스별로 정한다: 메일=스레드별 최신 처리(메일함 MailStore.threads와 같은 기준), 채팅=대화,
문서=무역 문서. 소스 상태를 화면 어휘(running·needs_input·needs_approval·completed·attention·skipped)로
정규화해 돌려주고, 메일 상세의 실행 과정은 runlog의 마스킹·표시 규칙을 그대로 재사용한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.auth.supabase import bearer_user_id
from app.db.mailbox import MailStore
from app.db.models import ProcessedMessage, TradeDocument
from app.runlog.export import load_run, run_records
# 실행 기록 화면과 같은 라벨·요약·집계 규칙을 함께 쓴다(화면마다 다르게 해석하지 않는다).
from app.runlog.router import END_LABELS, _counts, _event_rows

router = APIRouter(prefix="/api/status", tags=["status"])

NO_STORE = {"Cache-Control": "private, no-store"}

# 소스 상태 → 화면 상태. 여기 없는 값(needs_review·error·failed 등)은 '확인 필요'로 센다.
MAIL_STATES = {"processing": "running", "awaiting_approval": "needs_approval", "needs_input": "needs_input",
               "sent": "completed", "ignored": "skipped"}
CHAT_STATES = {"running": "running", "needs_input": "needs_input", "needs_approval": "needs_approval",
               "completed": "completed"}
DOC_STATES = {"needs_input": "needs_input", "ready": "needs_approval", "sent": "completed"}


def _run_ids(database, owner, row_ids):
    with database.session() as session:
        return dict(session.execute(select(ProcessedMessage.id, ProcessedMessage.run_id).where(
            ProcessedMessage.user_id == owner, ProcessedMessage.id.in_(row_ids))).all())


def mail_tasks(database, owner):
    items = MailStore(database).threads(owner)["items"]
    runs = _run_ids(database, owner, [item["id"] for item in items])
    return [{"kind": "mail", "id": f"mail-{item['thread_id']}", "thread_id": item["thread_id"],
             "run_id": runs.get(item["id"]), "title": item["subject"], "sub": item["from_addr"],
             "state": MAIL_STATES.get(item["status"], "attention"), "raw_status": item["status"],
             "notice": item["notice"], "at": item["received_at"]} for item in items]


def chat_tasks(agent_store, owner):
    return [{"kind": "chat", "id": row["id"], "title": row["title"],
             "state": CHAT_STATES.get(row["status"], "attention"), "raw_status": row["status"],
             "at": row["updated_at"]} for row in agent_store.list(owner)]


def doc_tasks(database, owner, limit=20):
    with database.session() as session:
        rows = list(session.scalars(select(TradeDocument).where(TradeDocument.user_id == owner)
                     .order_by(TradeDocument.created_at.desc()).limit(limit)))
    return [{"kind": "doc", "id": f"doc-{row.id}", "doc_id": row.id, "doc_kind": row.doc_kind,
             "doc_no": row.doc_no, "title": row.doc_no, "revision": row.revision,
             "state": DOC_STATES.get(row.status, "attention"), "raw_status": row.status,
             "at": row.created_at.isoformat()} for row in rows]


@router.get("/tasks")
def tasks(request: Request, owner: int = Depends(bearer_user_id)):
    merged = (mail_tasks(request.app.state.database, owner)
              + chat_tasks(request.app.state.agent.store, owner)
              + doc_tasks(request.app.state.database, owner))
    merged.sort(key=lambda task: task["at"] or "", reverse=True)
    return JSONResponse({"tasks": merged}, headers=NO_STORE)


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request, owner: int = Depends(bearer_user_id)):
    """메일 실행의 과정 한 건. 본인 실행만, runlog와 같은 마스킹으로 돌려준다."""
    loaded = load_run(request.app.state.database, owner, run_id)
    if loaded is None:
        raise HTTPException(404, detail="실행 기록을 찾을 수 없습니다")
    run, *events = run_records(*loaded)
    summary = {key: run[key] for key in ("run_id", "started_at", "ended_at", "end_reason", "duration_ms", "mode")}
    summary["end_label"] = END_LABELS.get(run["end_reason"], run["end_reason"])
    return JSONResponse({"run": summary, "events": _event_rows(run, events),
                         "counts": _counts(events)}, headers=NO_STORE)
