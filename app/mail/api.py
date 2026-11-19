"""React 메일함의 Bearer 전용 API. 기존 승인 서비스가 발송을 담당한다."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from app.auth.supabase import bearer_user_id
from app.db.mailbox import MailStore
from app.services import mailbox
from app.mail import attachments, compose, followups

router = APIRouter(prefix="/api/mail", tags=["mail"])


def _reply(function, *args, **kwargs):
    try:
        data = function(*args, **kwargs)
        if isinstance(data, bytes):
            return Response(data, media_type="application/pdf", headers={"Cache-Control": "private, no-store"})
        return JSONResponse(data, headers={"Cache-Control": "private, no-store"})
    except mailbox.MailError as error:
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status, headers={"Cache-Control": "private, no-store"})


@router.get("/compose-drafts/{draft_id}")
def read_compose(request: Request, draft_id: str, user_id: int = Depends(bearer_user_id)):
    return _reply(compose.read_draft, request.app.state.database, user_id, draft_id)


@router.put("/compose-drafts/{draft_id}")
def edit_compose(request: Request, draft_id: str, body: compose.EditComposeInput,
                 user_id: int = Depends(bearer_user_id)):
    return _reply(compose.revise_draft, request.app.state.database, user_id, draft_id, body)


@router.get("/threads")
def threads(request: Request, user_id: int = Depends(bearer_user_id),
            status: Literal["processing", "awaiting_approval", "sent", "error", "ignored", "needs_review"] | None = None,
            q: str = Query("", max_length=200), cursor: int | None = Query(None, gt=0)):
    return _reply(MailStore(request.app.state.database).threads, user_id, status=status, query=q, cursor=cursor)


@router.get("/threads/{thread_id}/messages/{message_id}/attachments/{part_id}")
def attachment(request: Request, thread_id: str, message_id: str, part_id: str,
               user_id: int = Depends(bearer_user_id)):
    try:
        content, filename = attachments.read_file(request.app.state.database, request.app.state.google_access,
                                                  user_id, thread_id, message_id, part_id)
    except mailbox.MailError as error:
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status, headers={"Cache-Control": "private, no-store"})
    return Response(content, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/followups")
def list_followups(request: Request, due_only: bool = False, cursor: int | None = Query(None, gt=0),
                   user_id: int = Depends(bearer_user_id)):
    return _reply(followups.list_items, request.app.state.database, user_id, due_only=due_only, cursor=cursor)


@router.delete("/followups/{followup_id}")
def cancel_followup(request: Request, followup_id: int, user_id: int = Depends(bearer_user_id)):
    return _reply(followups.cancel, request.app.state.database, user_id, followup_id)


@router.get("/threads/{thread_id}")
def thread(request: Request, thread_id: str, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.read_thread, MailStore(request.app.state.database), user_id, thread_id)


@router.post("/messages/{message_id}/process")
def process(request: Request, message_id: int, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.process_manually, request.app.state.google_access,
                  MailStore(request.app.state.database), user_id, message_id, graph=request.app.state.graph)


class SendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = None
    expected_subject: str | None = None
    expected_body: str | None = None


class EditCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    body: str
    expected_subject: str
    expected_body: str


@router.put("/candidates/{candidate_id}")
def edit_candidate(request: Request, candidate_id: int, body: EditCandidateInput,
                   user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.edit_candidate, MailStore(request.app.state.database), user_id,
                  candidate_id, subject=body.subject, body=body.body,
                  expected_subject=body.expected_subject, expected_body=body.expected_body)


class QuotePrices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prices: dict[str, str]


@router.post("/quotes/{quote_id}/prices")
def quote_prices(request: Request, quote_id: int, body: QuotePrices, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.complete_quote_prices, MailStore(request.app.state.database), user_id, quote_id, body.prices)


@router.get("/quotes/{quote_id}/preview.pdf")
def quote_preview(request: Request, quote_id: int, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.quote_pdf, MailStore(request.app.state.database), user_id, quote_id)


@router.get("/candidates/{candidate_id}/preview")
def preview(request: Request, candidate_id: int, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.preview_candidate, request.app.state.google_access,
                  MailStore(request.app.state.database), user_id, candidate_id)


@router.post("/candidates/{candidate_id}/send")
def send(request: Request, candidate_id: int, body: SendInput, user_id: int = Depends(bearer_user_id)):
    return _reply(mailbox.send_candidate, request.app.state.google_access,
                  MailStore(request.app.state.database), user_id, candidate_id,
                  storage=request.app.state.storage, revision=body.revision,
                   expected_subject=body.expected_subject, expected_body=body.expected_body)
