"""공급자 정보·품목 단가표 설정(계획 11절)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.db.models import CompanyProfile, PriceListItem, User
from app.quote.calc import price
from app.web.deps import current_user_id

router = APIRouter()


@router.get("/settings")
def settings(request: Request, user_id: int = Depends(current_user_id)):
    with request.app.state.database.session() as session:
        company = session.get(CompanyProfile, user_id)
        prices = session.scalars(select(PriceListItem).where(
            PriceListItem.user_id == user_id,
        ).order_by(PriceListItem.item_name)).all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/settings.html", context={"company": company, "prices": prices},
    )


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
        ))
        if row is None:
            row = PriceListItem(user_id=user_id, item_name=item_name.strip())
            session.add(row)
        row.unit, row.unit_price = unit.strip() or None, price(unit_price)
    return RedirectResponse("/settings", status_code=303)
