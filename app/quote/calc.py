"""견적서 단가 선택·원 단위 정수 계산(계약 4.3·12.2절)."""

from copy import deepcopy
from datetime import date, timedelta

from app.config import LIMITS


def price(value) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("단가는 0 이상의 원 단위 정수여야 합니다")
    return value


def recalculate(draft: dict) -> dict:
    result = deepcopy(draft)
    for line in result["lines"]:
        line["amount"] = (line["quantity"] * price(line["unit_price"])
                          if line["unit_price"] is not None else None)
    result["missing_prices"] = [line["item_name"] for line in result["lines"]
                                if line["unit_price"] is None]
    supply = None if result["missing_prices"] else sum(line["amount"] for line in result["lines"])
    # float를 거치지 않아 큰 금액도 정확하다. VAT_RATE=0.10(계약 3.4절).
    result["supply_amount"] = supply
    result["vat"] = None if supply is None else supply // 10
    result["total"] = None if supply is None else supply + result["vat"]
    result["status"] = "needs_price" if result["missing_prices"] else "ready"
    return result


def build_draft(terms: dict, company: dict | None, price_list: list[dict], *,
                quote_no: str, quote_date: date) -> dict:
    if not terms.get("customer_name") or not terms.get("items"):
        raise ValueError("거래처와 품목이 필요합니다")
    lines = []
    for item in terms["items"]:
        quantity = item.get("quantity")
        if not item.get("item_name") or type(quantity) is not int or quantity <= 0:
            raise ValueError("품목명과 양의 정수 수량이 필요합니다")
        unit_price, source = item.get("unit_price"), None
        if unit_price is not None:
            unit_price, source = price(unit_price), "thread"
        else:
            entry = next((row for row in price_list
                          if row.get("item_name") == item["item_name"]
                          and row.get("unit") == item.get("unit")), None)
            if entry is not None:
                unit_price, source = price(entry["unit_price"]), "price_list"
        lines.append({"item_name": item["item_name"], "quantity": quantity,
                      "unit": item.get("unit"), "unit_price": unit_price,
                      "amount": None, "price_source": source})
    return recalculate({
        "quote_id": None, "quote_no": quote_no, "quote_date": quote_date.isoformat(),
        "valid_until": (quote_date + timedelta(days=LIMITS["QUOTE_VALID_DAYS"])).isoformat(),
        "supplier": company or {}, "customer_name": terms["customer_name"], "lines": lines,
    })


def fill_prices(draft: dict, values: dict[int, int]) -> dict:
    result = deepcopy(draft)
    if draft["status"] != "needs_price":
        raise ValueError("단가 입력을 기다리는 견적서만 수정할 수 있습니다")
    missing = {i for i, line in enumerate(result["lines"]) if line["unit_price"] is None}
    if set(values) != missing:
        raise ValueError("빠진 단가를 모두 입력해 주세요")
    for index, value in values.items():
        result["lines"][index].update(unit_price=price(value), price_source="user")
    return recalculate(result)
