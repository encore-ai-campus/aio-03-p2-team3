"""견적서 확인·단가 입력·PDF 미리보기(계획 11절)."""

from typing import Annotated
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.db.models import Quote, ReplyCandidate
from app.quote.calc import fill_prices
from app.quote.pdf import render_quote_pdf
from app.services.approval import send_approved_quote
from app.auth.deps import current_user_id
from app.mail.candidates import APPROVAL_NOTICES

router = APIRouter()


def owned_quote(session, quote_id, user_id, *, lock=False):
    query = select(Quote).where(Quote.id == quote_id, Quote.user_id == user_id)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "견적서를 찾을 수 없습니다")
    return row


@router.get("/quotes/{quote_id}")
def quote_detail(quote_id: int, request: Request, notice: str | None = None,
                 user_id: int = Depends(current_user_id)):
    with request.app.state.database.session() as session:
        row = owned_quote(session, quote_id, user_id)
        candidates = session.scalars(select(ReplyCandidate).where(
            ReplyCandidate.user_id == user_id, ReplyCandidate.quote_id == row.id,
            ReplyCandidate.run_id == row.run_id, ReplyCandidate.thread_id == row.thread_id,
            ReplyCandidate.kind == "quote", ReplyCandidate.status.in_(("pending", "send_failed")),
        ).order_by(ReplyCandidate.id)).all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/quote.html", context={"quote": row, "candidates": candidates,
            "notice": ({"needs_price": ("빠진 단가를 입력한 뒤 승인해 주세요", "warn"),
                         **APPROVAL_NOTICES}).get(notice or "", (None, None))[0]},
    )


@router.post("/quotes/{quote_id}/prices")
async def save_prices(quote_id: int, request: Request, user_id: int = Depends(current_user_id)):
    form = await request.form()
    with request.app.state.database.session() as session:
        row = owned_quote(session, quote_id, user_id, lock=True)
        if row.status != "needs_price":
            raise HTTPException(409, "단가 입력을 기다리는 견적서만 수정할 수 있습니다")
        try:
            # 품목명이 중복돼도 행 번호로 구분한다. 합의 단가·기존 단가는 변경하지 않는다.
            keys = {f"price_{i}" for i, line in enumerate(row.draft["lines"])
                    if line["unit_price"] is None}
            if set(form) != keys or any(len(form.getlist(key)) != 1 for key in keys):
                raise ValueError()
            values = {int(key[6:]): int(form[key]) for key in keys if str(form[key]).isdecimal()}
            row.draft = fill_prices(row.draft, values)
            row.status = row.draft["status"]
        except (ValueError, TypeError):
            raise HTTPException(400, "빠진 단가를 모두 0 이상의 원 단위 정수로 입력해 주세요") from None
    return RedirectResponse(f"/quotes/{quote_id}", status_code=303)


@router.get("/quotes/{quote_id}/preview.pdf")
def preview(quote_id: int, request: Request, user_id: int = Depends(current_user_id)):
    with request.app.state.database.session() as session:
        row = owned_quote(session, quote_id, user_id)
        draft = row.draft
    filename = urlquote(f"견적서_{draft['quote_no']}.pdf")
    return Response(render_quote_pdf(draft), media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}", "Cache-Control": "no-store",
    })


@router.post("/quotes/{quote_id}/approve")
def approve(quote_id: int, candidate_id: Annotated[int, Form()], request: Request,
            user_id: int = Depends(current_user_id)):
    result = send_approved_quote(user_id, quote_id, candidate_id, access=request.app.state.google_access)
    if result.outcome == "not_found":
        raise HTTPException(404, "견적서와 답장 후보를 찾을 수 없습니다")
    return RedirectResponse(f"/quotes/{quote_id}?notice={result.outcome}", status_code=303)
