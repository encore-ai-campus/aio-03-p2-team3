"""make_quote: 공급자·단가표를 읽고 견적서/무역서류 도구를 호출한다(계획 11절, 계약 15.6절).

`deal_terms["doc_kind"]`(없으면 "quote")로 도구를 고른다. 국내 견적서는 기존 `create_quote`,
무역서류(PI·PO·CI·PL)는 `create_trade_document`를 부르고 발행 회사(`company_profiles`)·
계좌(`company_bank_accounts`, 문서 통화 행 우선)·무역 단가표(`price_list_items` 무역 행)를 넘긴다.
"""

from sqlalchemy import select

from app.db.models import CompanyBankAccount, CompanyProfile, DealTerms, PriceListItem, Quote, TradeDocument
from app.graph.nodes.common import call_tool, failure_update
from app.graph.state import AgentState
from app.runlog.logger import current_database
from app.trade.settings.repository import trade_price_rows

# 무역서류 발행사 스냅숏 키(계약 15.7절 company_profiles 열).
ISSUER_FIELDS = ("company_name", "business_no", "ceo_name", "contact",
                 "legal_name_en", "address", "phone", "email", "registration_details")
# 원본 렌더러가 읽는 계좌 대문자 6키(계약 15.7절).
BANK_KEYS = ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")


def _issuer_snapshot(session, user_id: int) -> dict | None:
    row = session.get(CompanyProfile, user_id)
    if row is None:
        return None
    return {key: getattr(row, key) for key in ISSUER_FIELDS}


def _bank_snapshot(session, user_id: int, currency: str | None) -> dict | None:
    """문서 통화 행 우선(통화가 같은 행이 없으면 등록된 첫 행). 없으면 None(PI 하단 계좌 생략)."""
    rows = session.scalars(select(CompanyBankAccount).where(
        CompanyBankAccount.user_id == user_id).order_by(CompanyBankAccount.id)).all()
    if not rows:
        return None
    row = next((item for item in rows if currency and item.currency == currency), rows[0])
    return {"BENEFICIARY": row.beneficiary, "BANK_NAME": row.bank_name, "BRANCH": row.branch,
            "SWIFT": row.swift, "ACCOUNT_NUMBER": row.account_number,
            "BANK_ADDRESS": row.bank_address}


def make_quote(state: AgentState) -> dict:
    deal_terms = state["deal_terms"]
    if deal_terms is None:
        return failure_update(state, "make_quote", "invalid_input", "견적서를 만들 거래 항목이 없습니다")
    database = current_database()
    if deal_terms.get("doc_kind", "quote") != "quote":
        return _make_trade_document(state, deal_terms, database)
    with database.session() as session:
        company = session.get(CompanyProfile, state["user_id"])
        supplier = ({key: getattr(company, key) for key in
                     ("company_name", "business_no", "ceo_name", "contact")} if company else None)
        prices = [{"item_name": row.item_name, "unit": row.unit, "unit_price": row.unit_price}
                  for row in session.scalars(select(PriceListItem).where(
                      PriceListItem.user_id == state["user_id"],
                      PriceListItem.role.is_(None),  # 국내 견적서 행만(계약 15.7절, 무역 분기에서 읽음)
                  ))]
    result, update = call_tool(state, "make_quote", "create_quote", {
        "user_id": state["user_id"], "thread_id": state["thread_id"],
        "deal_terms": deal_terms, "company": supplier, "price_list": prices,
    }, {"items": len(deal_terms["items"]), "has_company": supplier is not None},
        kind_of_reply="quote")
    if not result.ok:
        return update
    with database.session() as session:
        row = session.scalar(select(Quote).where(Quote.id == result.value["quote_id"],
                                                 Quote.user_id == state["user_id"]))
        row.run_id = state["run_id"]
        row.deal_terms_id = session.scalar(select(DealTerms.id).where(
            DealTerms.user_id == state["user_id"], DealTerms.run_id == state["run_id"],
        ))
    return {**update, "quote_draft": result.value, "reply_mode": "quote"}


def _make_trade_document(state: AgentState, deal_terms: dict, database) -> dict:
    """무역서류 분기(계약 15.6절): 문서 종류별 가격·계산 규칙으로 초안을 저장한다."""
    with database.session() as session:
        issuer = _issuer_snapshot(session, state["user_id"])
        bank = _bank_snapshot(session, state["user_id"], deal_terms.get("currency"))
        price_rows = trade_price_rows(session, state["user_id"])
        deal_terms_id = session.scalar(select(DealTerms.id).where(
            DealTerms.user_id == state["user_id"], DealTerms.run_id == state["run_id"],
        ))
    result, update = call_tool(state, "make_quote", "create_trade_document", {
        "user_id": state["user_id"], "thread_id": state["thread_id"], "deal_terms": deal_terms,
        "company": issuer, "bank": bank, "price_list": price_rows,
        "run_id": state["run_id"], "deal_terms_id": deal_terms_id,
    }, {"doc_kind": deal_terms.get("doc_kind"), "items": len(deal_terms.get("items") or []),
        "has_issuer": issuer is not None, "has_bank": bank is not None,
        "price_rows": len(price_rows)}, kind_of_reply="quote")
    if not result.ok:
        return update
    with database.session() as session:
        # 저장 결과 상태(status)를 스냅숏과 같은 트랜잭션 조건으로 다시 확인한다(승인·발송은 밖에서).
        row = session.scalar(select(TradeDocument).where(
            TradeDocument.id == result.value["trade_doc_id"],
            TradeDocument.user_id == state["user_id"]))
        row.run_id = state["run_id"]  # save_trade_document이 이미 넣었지만 성찰 재실행에 대비해 확정한다
    return {**update, "trade_doc_draft": result.value, "reply_mode": "quote"}
