"""make_quote: 공급자·단가표를 읽고 create_quote를 호출한다(계획 11절)."""

from sqlalchemy import select

from app.db.models import CompanyProfile, DealTerms, PriceListItem, Quote
from app.graph.nodes.common import call_tool, failure_update
from app.graph.state import AgentState
from app.runlog.logger import current_database


def make_quote(state: AgentState) -> dict:
    if state["deal_terms"] is None:
        return failure_update(state, "make_quote", "invalid_input", "견적서를 만들 거래 항목이 없습니다")
    database = current_database()
    with database.session() as session:
        company = session.get(CompanyProfile, state["user_id"])
        supplier = ({key: getattr(company, key) for key in
                     ("company_name", "business_no", "ceo_name", "contact")} if company else None)
        prices = [{"item_name": row.item_name, "unit": row.unit, "unit_price": row.unit_price}
                  for row in session.scalars(select(PriceListItem).where(
                      PriceListItem.user_id == state["user_id"],
                  ))]
    result, update = call_tool(state, "make_quote", "create_quote", {
        "user_id": state["user_id"], "thread_id": state["thread_id"],
        "deal_terms": state["deal_terms"], "company": supplier, "price_list": prices,
    }, {"items": len(state["deal_terms"]["items"]), "has_company": supplier is not None},
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
