"""공급자 정보·품목 단가표 설정(계획 11절)과 자가 성찰 켬/끔(계획 12절)."""

from typing import Annotated
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.db.models import CompanyProfile, PriceListItem, User
from app.quote.calc import price
from app.auth.deps import check_session_csrf, current_user_id
from app.llm.client import OpenAIKeyError
from app.services.openai_keys import UserKeyAccess, delete_key, key_registered, save_key

router = APIRouter()


@router.get("/settings")
def settings(request: Request, user_id: int = Depends(current_user_id)):
    config = request.app.state.settings
    local_mode = config.ai_runtime == "local"
    csrf_token = request.session.setdefault("trade_csrf", secrets.token_urlsafe(32))
    with request.app.state.database.session() as session:
        company = session.get(CompanyProfile, user_id)
        prices = session.scalars(select(PriceListItem).where(
            PriceListItem.user_id == user_id,
            PriceListItem.role.is_(None),  # 국내 견적서 행만(무역 행은 계약 15.7절, 별도)
        ).order_by(PriceListItem.item_name)).all()
        reflection_enabled = session.scalar(select(User.reflection_enabled).where(User.id == user_id))
        user = session.get(User, user_id)
        local_sub = user.google_sub if local_mode and user and user.last_login_at is not None else None
    local_error = None
    from app.worker.service import status as worker_status
    from app.worker.adapter import ERRORS
    worker = None if local_mode else worker_status(request.app.state.database, user_id)
    if local_mode:
        try:
            UserKeyAccess(request.app.state.database, user_id, None, config).read()
        except OpenAIKeyError as error:
            local_error = error.message
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/settings.html",
        context={"company": company, "prices": prices, "reflection_enabled": bool(reflection_enabled),
                 "local_mode": local_mode, "local_google_sub": local_sub, "local_key_error": local_error,
                 "openai_registered": (local_error is None) if local_mode else key_registered(request.app.state.database, user_id, settings=config),
                 "openai_storage_ready": request.app.state.google_access.cipher is not None,
                 "csrf_token": csrf_token,
                 "worker": worker, "worker_https": config.app_base_url.startswith("https://"),
                 "worker_google_sub": user.google_sub if user and user.last_login_at is not None else None,
                 "worker_errors": {kind: message for kind, (_, message, _) in ERRORS.items()},
                 "key_notice": {"saved": "OpenAI API 키를 저장했습니다. 키의 유효성은 실제 AI 요청 시 확인합니다.",
                                "deleted": "OpenAI API 키를 삭제했습니다. 이후 AI 요청은 차단됩니다."}.get(
                                    request.query_params.get("key_notice", ""))},
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/settings/openai-key")
def save_openai_key(request: Request, api_key: Annotated[str, Form()] = "",
                    csrf_token: Annotated[str, Form()] = "", user_id: int = Depends(current_user_id)):
    check_session_csrf(request, csrf_token)
    try:
        save_key(request.app.state.database, user_id, api_key, request.app.state.google_access.cipher,
                 settings=request.app.state.settings)
    except OpenAIKeyError as error:
        # Form에 길이/패턴 검증을 붙이면 422 응답이 입력한 비밀값을 다시 보여 줄 수 있다.
        raise HTTPException(error.status_code, error.message) from None
    return RedirectResponse("/settings?key_notice=saved", status_code=303,
                            headers={"Cache-Control": "private, no-store"})


@router.post("/settings/openai-key/delete")
def delete_openai_key(request: Request, csrf_token: Annotated[str, Form()] = "",
                      user_id: int = Depends(current_user_id)):
    check_session_csrf(request, csrf_token)
    try:
        delete_key(request.app.state.database, user_id, settings=request.app.state.settings)
    except OpenAIKeyError as error:
        raise HTTPException(error.status_code, error.message) from None
    return RedirectResponse("/settings?key_notice=deleted", status_code=303,
                            headers={"Cache-Control": "private, no-store"})


@router.post("/settings/reflection")
def save_reflection(request: Request, enabled: Annotated[str, Form()] = "",
                    user_id: int = Depends(current_user_id)):
    """자가 성찰 켬/끔(계획 12절). 다음 실행부터 `start_run()`이 이 값을 쓴다(계약 12.3절)."""
    with request.app.state.database.session() as session:
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise HTTPException(404, "사용자를 찾을 수 없습니다")
        user.reflection_enabled = enabled == "on"
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/company")
def save_company(request: Request, company_name: Annotated[str, Form(min_length=1, max_length=200)],
                 business_no: Annotated[str, Form(max_length=100)] = "",
                 ceo_name: Annotated[str, Form(max_length=100)] = "",
                 contact: Annotated[str, Form(max_length=300)] = "",
                 user_id: int = Depends(current_user_id)):
    if not company_name.strip():
        raise HTTPException(400, "상호를 입력해 주세요")
    with request.app.state.database.session() as session:
        session.scalar(select(User).where(User.id == user_id).with_for_update())
        row = session.get(CompanyProfile, user_id)
        if row is None:
            row = CompanyProfile(user_id=user_id)
            session.add(row)
        row.company_name = company_name.strip()
        row.business_no = business_no.strip()
        row.ceo_name = ceo_name.strip()
        row.contact = contact.strip()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/prices")
def save_price(request: Request, item_name: Annotated[str, Form(min_length=1, max_length=200)],
               unit_price: Annotated[int, Form(ge=0, le=2**63 - 1)],
               unit: Annotated[str, Form(max_length=100)] = "",
               user_id: int = Depends(current_user_id)):
    if not item_name.strip():
        raise HTTPException(400, "품목명을 입력해 주세요")
    with request.app.state.database.session() as session:
        session.scalar(select(User).where(User.id == user_id).with_for_update())
        row = session.scalar(select(PriceListItem).where(
            PriceListItem.user_id == user_id, PriceListItem.item_name == item_name.strip(),
            PriceListItem.role.is_(None),  # 국내 견적서 행만 저장·수정(무역 행은 계약 15.7절)
        ))
        if row is None:
            row = PriceListItem(user_id=user_id, item_name=item_name.strip())
            session.add(row)
        row.unit, row.unit_price = unit.strip() or None, price(unit_price)
    return RedirectResponse("/settings", status_code=303)
