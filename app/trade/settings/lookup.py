"""등록 단가와 거래처의 읽기 규칙. 호출자가 본인 조회 행을 전달한다."""
from app.trade.common.counterparties import name_key
from app.trade.common.product_search import search_products, search_tokens


def match_counterparties(query: str, profiles: list[dict]) -> list[dict]:
    key = name_key(query)
    if not key:
        return []
    exact = []
    partial = []
    for profile in profiles:
        names = [profile["company_key"], profile["legal_name"], *profile["aliases"]]
        keys = {name_key(name) for name in names}
        if key in keys or query.casefold() == (profile.get("email") or "").casefold():
            exact.append(profile)
        elif any(key in value for value in keys):
            partial.append(profile)
    return exact or partial


def contacts(query: str, profiles: list[dict]) -> dict:
    matched = match_counterparties(query, profiles)
    fields = ("company_key", "legal_name", "contact", "email", "phone", "address")
    return {"counterparties": [{key: item[key] for key in fields} for item in matched[:10]],
            "total": len(matched)}


def _identity(row: dict) -> tuple:
    code = "".join(search_tokens(row.get("product_code")))
    return (code or name_key(row["item_name"]), row["capacity"], row["role"], row["currency"])


def catalog_prices(*, product: str, role: str | None, currency: str | None, counterparty: str | None,
                   prices: list[dict], profiles: list[dict]) -> dict:
    related = match_counterparties(counterparty, profiles) if counterparty else []
    if len(related) > 1:
        return {"prices": [], "price_status": "choose_counterparty", **contacts(counterparty, profiles)}
    party_key = name_key(related[0]["company_key"] if related else counterparty)
    rows = [row for row in prices if row["unit_price_text"] is not None
            and (role is None or row["role"] == role)
            and (currency is None or row["currency"] == currency)
            and (not counterparty or not row.get("party_key") or name_key(row["party_key"]) == party_key)]
    code = "".join(search_tokens(product))
    exact_ids = {row["id"] for row in prices if code and code == "".join(search_tokens(row["product_code"]))}
    if exact_ids:
        matched = [row for row in rows if row["id"] in exact_ids]
    else:
        ranked = search_products(product, [{**row, "source_code": row["product_code"]} for row in rows])
        products = {_identity(item["product"])[:2] for item in ranked}
        matched = [row for row in rows if _identity(row)[:2] in products]
    if counterparty:
        specific = {_identity(row) for row in matched if row.get("party_key")}
        matched = [row for row in matched if row.get("party_key") or _identity(row) not in specific]
    names = {name_key(item["company_key"]): item["legal_name"] for item in profiles}
    result = [{
        **{key: row[key] for key in ("id", "item_name", "product_code", "capacity", "role",
                                    "currency", "unit", "price_basis")},
        "unit_price": row["unit_price_text"],
        "scope": "counterparty" if row.get("party_key") else "common",
        "counterparty": names.get(name_key(row.get("party_key")), row.get("party_key")) or None,
    } for row in matched[:10]]
    return {"prices": result, "total": len(matched), "price_status": "found" if result else "not_found"}
