"""무역 단가표·거래처 설정 조회(kekorea-port 3절 B, 계약 15.7절).

`price_list_items` 무역 행(role이 NULL이 아닌 행)과 `counterparties` 표를 문서 생성 도구 입력
(`build_trade_catalog`·`apply_company_profiles`가 받는 dict)으로 바꿔 돌려준다. 조회는 모두
`user_id`로 거른다. 설정 화면에서 무역 행·거래처를 저장하는 일은 화면 작업 범위 밖이다.
"""
from sqlalchemy import select

from app.db.models import Counterparty, PriceListItem


def trade_price_rows(session, user_id):
    """본인 무역 단가 행을 `build_trade_catalog` 입력(dict) 목록으로 돌려준다."""
    rows = session.scalars(select(PriceListItem).where(
        PriceListItem.user_id == user_id, PriceListItem.role.is_not(None),
    ).order_by(PriceListItem.id)).all()
    return [{"id": row.id, "item_name": row.item_name, "unit": row.unit, "role": row.role,
             "currency": row.currency, "price_basis": row.price_basis,
             "product_code": row.product_code, "capacity": row.capacity,
             "unit_price_text": row.unit_price_text, "party_key": row.party_key}
            for row in rows]


def counterparty_profiles(session, user_id):
    """본인 거래처를 `apply_company_profiles` 입력(원본 FIELDS 키) 목록으로 돌려준다."""
    rows = session.scalars(select(Counterparty).where(
        Counterparty.user_id == user_id,
    ).order_by(Counterparty.company_key)).all()
    return [{"company_key": row.company_key, "legal_name": row.legal_name,
             "aliases": row.aliases if isinstance(row.aliases, list) else [],
             "address": row.address, "contact": row.contact, "phone": row.phone,
             "email": row.email, "registration_details": row.registration_details,
             "default_ship_to": row.default_ship_to, "ship_to_phone": row.ship_to_phone}
            for row in rows]
