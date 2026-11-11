"""사용자별 단가표 카탈로그 가격 적용(kekorea-port 3절 B).

원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py — 복사한 뒤 계약 15.4절대로 고침.
- `load_local_seed`·`load_local_catalog`·`load_supabase_catalog`·회사 가격 시드는 없애고,
  대신 `build_trade_catalog(rows)`가 `price_list_items` 무역 행(계약 15.7절)을 원본 seed 구조로 바꾼다.
- 회사 고정값을 일반화했다[임시: 협의 5·7·8]: 문서 종류별 가격 출처는 그대로(PO 매입가, PI 구매처별
  판매가)이되, 카탈로그 가격 적용 여부는 문서 상대방(PO는 seller, 그 밖은 buyer)의 이름 키와 가격 행
  `party_key`의 일치로 판정하고 일치 행이 없으면 공통 가격 행(빈 문자열)으로 다시 찾는다.
- PO의 통화 KRW 강제를 없앴다. 문서에 명시된 통화가 있으면 그 통화의 행만 쓰고, 없을 때 그 상대방·
  품목의 행 통화가 하나뿐이면 그 통화로 정한다(원본 `_catalog_currency_inferred` 표시 규칙 유지).
- 안내 문구의 회사 이름(ECLADO 등)은 카탈로그 일반 문구로 바꿨다(이식 규칙: 회사 고유 값 금지).
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from app.trade.counterparties import name_key
from app.trade.product_matching import match_product


def _empty_catalog():
    return {"products": [], "purchase_prices": [], "buyer_prices": []}


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py load_* 없앰을 대신하는 새 함수(계약 15.4절)
def build_trade_catalog(rows):
    """`price_list_items` 무역 행 목록을 원본 seed 구조(products·purchase_prices·buyer_prices)로 바꾼다.

    같은 품목의 매입·판매·통화별 가격 행이 여러 개여도 product는 하나다(item_name 기준 중복 제거.
    product id는 그 품목 행들 중 가장 작은 행 id, capacity·source_code는 비어 있지 않은 첫 값).
    올바르지 않은 행은 단가 값을 메시지에 노출하지 않고 ValueError로 막는다(원본 카탈로그 불러오기의
    오류 처리 규칙 유지).
    """
    parsed = []
    for row in rows or []:
        role = row.get("role")
        if role not in ("purchase", "sale"):
            raise ValueError("무역 단가표 행의 role은 purchase 또는 sale이어야 합니다")
        name = str(row.get("item_name") or "").strip()
        if not name:
            raise ValueError("무역 단가표 행에 품목명이 필요합니다")
        currency = str(row.get("currency") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError(f"무역 단가표 행의 통화는 3자리 ISO 코드여야 합니다: {name}")
        price_text = str(row.get("unit_price_text") if row.get("unit_price_text") is not None
                         else row.get("unit_price") or "").strip()
        try:
            amount = Decimal(price_text.replace(",", ""))
        except (InvalidOperation, ValueError):
            raise ValueError(f"무역 단가표 행의 단가가 숫자가 아닙니다: {name}") from None
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"무역 단가표 행의 단가가 올바르지 않습니다: {name}") from None
        parsed.append({"role": role, "name": name, "id": row.get("id"), "currency": currency,
                       "price_text": price_text, "price_basis": row.get("price_basis"),
                       "capacity": row.get("capacity") or None,
                       "code": row.get("product_code") or None,
                       "party_key": str(row.get("party_key") if row.get("party_key") is not None else "").strip()})
    products = {}
    for entry in parsed:
        product = products.get(entry["name"])
        if product is None:
            product = {"id": entry["id"], "item_name": entry["name"],
                       "capacity": entry["capacity"], "source_code": entry["code"]}
            products[entry["name"]] = product
            continue
        if entry["id"] is not None and (product["id"] is None or entry["id"] < product["id"]):
            product["id"] = entry["id"]
        if product["capacity"] is None and entry["capacity"]:
            product["capacity"] = entry["capacity"]
        if product["source_code"] is None and entry["code"]:
            product["source_code"] = entry["code"]
    purchase_prices, buyer_prices = [], []
    for entry in parsed:
        price = {"product_id": products[entry["name"]]["id"], "currency": entry["currency"],
                 "unit_price": entry["price_text"], "price_basis": entry["price_basis"]}
        if entry["role"] == "purchase":
            price["supplier_key"] = entry["party_key"]
            purchase_prices.append(price)
        else:
            price["buyer_key"] = entry["party_key"]
            buyer_prices.append(price)
    return {"products": list(products.values()), "purchase_prices": purchase_prices,
            "buyer_prices": buyer_prices}


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py match_eclado_product → match_catalog_product(계약 15.4절 개명)
def match_catalog_product(name, capacity=None, products=None, product_code=None):
    """Resolve a complete catalog name, verified SKU and equivalent size notation."""
    products = list(products or [])
    return match_product(name, capacity, products, product_code)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py resolve_price
def resolve_price(product_id, prices=None, role="sale", currency=None, party_key=None):
    """Resolve a catalog price only on exact product, role and currency."""
    if prices is None:
        prices = {}
    table = "buyer_prices" if role == "sale" else "purchase_prices"
    party_field = "buyer_key" if role == "sale" else "supplier_key"
    rows = [p for p in prices.get(table, []) if p.get("product_id") == product_id and
            (currency is None or p.get("currency") == currency) and
            (party_key is None or str(p.get(party_field) or "").upper() == party_key.upper())]
    if len(rows) != 1:
        return None
    return rows[0] if len(rows) == 1 else None


def _alias_key(alias):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(alias or "")).casefold())


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py is_eclado_supplier → is_supplier_alias
# (회사 고정 별칭 대신 사용자 거래처 별칭 목록[임시: 협의 5]. 원본처럼 별칭 키가 이름 키 안에
# 들어 있으면 인정하고 원문 법인명은 바꾸지 않는다.)
def is_supplier_alias(name, aliases):
    """Recognize the configured supplier aliases without rewriting the legal name."""
    key = _alias_key(name)
    if not key:
        return False
    return any(alias_key and alias_key in key for alias_key in (_alias_key(a) for a in aliases or ()))


def _matching_party_key(rows, party_field, counterparty_key):
    """거래처 이름 키와 일치하는 가격 행 키를 찾는다. 없으면 공통 가격 행(빈 문자열)을 돌려준다."""
    if counterparty_key:
        for row in rows or []:
            stored = str(row.get(party_field) or "").strip()
            if stored and name_key(stored) == counterparty_key:
                return stored
    if any(str(row.get(party_field) or "").strip() == "" for row in rows or []):
        return ""
    return None


def _party_labels(rows, party_field, product_id):
    labels = sorted({str(row.get(party_field) or "").strip() for row in rows or []
                     if row.get("product_id") == product_id and str(row.get(party_field) or "").strip()})
    return ", ".join(labels) if labels else "configured counterparties"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py apply_catalog_product_matches
# (안내 문구의 회사 이름만 일반 문구로 바꿨다)
def apply_catalog_product_matches(draft, catalog=None):
    """Attach confident catalog product identities without changing document prices."""
    from app.trade.samples import is_manual_sample
    catalog = catalog if catalog is not None else _empty_catalog()
    products = catalog.get("products", [])
    product_ids = {product.get("id") for product in products}
    draft["missing_fields"] = [
        entry for entry in draft.get("missing_fields", [])
        if not (str(entry).startswith("Exact catalog product match for ")
                and str(entry).endswith("; capacity/SKU may be needed"))
    ]
    pending = draft.setdefault("pending_confirmations", [])
    pending[:] = [entry for entry in pending if not str(entry).startswith(
        ("Confirm product annotation for ", "Double-check this product:"))]

    items = draft.get("items", [])
    matches = [match_catalog_product(item.get("product_name"), item.get("capacity"), products,
                                     item.get("product_code"))
               for item in items]
    if (draft.get("document_type") == "PL" and draft.get("product_family") != "cosmetics"
            and not any(match["status"] in {"matched", "suggested", "ambiguous"} for match in matches)):
        return draft

    for item, match in zip(items, matches):
        if is_manual_sample(draft, item):
            continue
        if match["status"] == "matched":
            item["product_id"] = match["product"]["id"]
            confirmation = match.get("confirmation")
            if confirmation and confirmation not in pending:
                pending.append(confirmation)
            continue

        if item.get("product_id") in product_ids:
            item.pop("product_id", None)
        name = item.get("product_name") or "item"
        suggestions = match.get("suggestions", [])
        if suggestions:
            candidate = suggestions[0]
            message = (f"Double-check this product: {name} may be "
                       f"{candidate['product']['item_name']} ({candidate['similarity']:.0%} similarity). "
                       "Confirm the source or keep the manually entered name.")
        else:
            message = (f"Double-check this product: {name} has no unique catalog match. "
                       "Confirm the source or keep the manually entered name.")
        if message not in pending:
            pending.append(message)
        draft.setdefault("missing_fields", []).append(
            f"Exact catalog product match for {name}; capacity/SKU may be needed")
    return draft


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pricing.py apply_verified_eclado_prices
# → apply_verified_catalog_prices(계약 15.4절 이름 제외 규칙에 따라 개명. 회사 고정값 일반화 내용은
# 모듈 머리글 참고)
def apply_verified_catalog_prices(draft, catalog=None):
    """Replace candidate prices with exact user-catalog prices or mark the uncertainty."""
    if draft.get("document_type") in {"CI", "PL"}:
        return apply_catalog_product_matches(draft, catalog)
    from app.trade.samples import is_manual_sample
    catalog = catalog if catalog is not None else _empty_catalog()
    is_purchase_order = draft.get("document_type") == "PO"
    # Recompute catalog-owned warnings after the user completes buyer/product/currency fields.
    draft["missing_fields"] = [entry for entry in draft.get("missing_fields", []) if not (
        (str(entry).startswith("Exact catalog product match for ") and str(entry).endswith("; capacity/SKU may be needed"))
        or (str(entry).startswith("Confirm a transaction-specific price for ") and "; local catalog price is only for " in str(entry))
        or re.fullmatch(r"Verified \S+ catalog price for .+", str(entry)))]
    if is_purchase_order:
        buyer = draft.get("buyer") or {}
        seller = draft.get("seller") or {}
        draft["missing_fields"] = [
            entry for entry in draft["missing_fields"]
            if not (
                (str(entry) == "PO buyer legal name and address"
                 and buyer.get("legal_name") and buyer.get("address"))
                or (str(entry).casefold().endswith("supplier legal name and address")
                    and seller.get("legal_name") and seller.get("address"))
            )
        ]
    products = catalog.get("products", [])
    items = draft.get("items", [])
    if is_purchase_order:
        for item in items:
            basis = str(item.get("price_basis") or "").strip()
            basis = re.sub(r"^(?:USD|KRW|EUR|CNY)\s*(?:/\s*|PER\s+)?", "", basis, flags=re.I)
            basis = re.sub(r"^PER\s+", "", basis, flags=re.I)
            item["price_basis"] = basis or item.get("unit")
    # Vision extraction can label a cosmetics order as "other" when the image
    # shows products and sizes but no explicit category. An exact match of every
    # line against the catalog product master is stronger evidence and lets the
    # existing role/currency-specific price lookup proceed for both PI and PO.
    exact_matches = [match_catalog_product(item.get("product_name"), item.get("capacity"), products,
                                            item.get("product_code"))
                     for item in items]
    regular_matches = [match for item, match in zip(items, exact_matches) if not is_manual_sample(draft, item)]
    price_table = "purchase_prices" if draft.get("document_type") == "PO" else "buyer_prices"
    party_field = "supplier_key" if price_table == "purchase_prices" else "buyer_key"
    counterparty_role = "seller" if draft.get("document_type") == "PO" else "buyer"
    counterparty_name = str((draft.get(counterparty_role) or {}).get("legal_name") or "").strip()
    counterparty_key = name_key(counterparty_name)
    price_rows = catalog.get(price_table, []) or []
    # 계약 15.4절: 가격 적용 여부는 상대방 이름 키와 가격 행 party_key의 일치로 판정한다.
    stored_party_key = _matching_party_key(price_rows, party_field, counterparty_key)
    party_matches = stored_party_key is not None
    if is_purchase_order and items:
        draft["product_family"] = "cosmetics"
    elif regular_matches and draft.get("product_family") != "cosmetics":
        all_matched = all(match["status"] == "matched" for match in regular_matches)
        recognized_order = (draft.get("document_type") in {"PO", "PI", "CI"} and party_matches
                            and draft.get("product_family") in (None, "", "other")
                            and any(match["status"] in {"matched", "suggested"} for match in regular_matches))
        if all_matched or recognized_order:
            draft["product_family"] = "cosmetics"
    pending = draft.setdefault("pending_confirmations", [])
    pending[:] = [entry for entry in pending if not str(entry).startswith(
        ("Confirm product annotation for ", "Double-check this product:"))]
    pending[:] = [entry for entry in pending if not str(entry).startswith(
        "The seller was not supplied.")]
    if not party_matches and draft.get("_catalog_currency_inferred"):
        draft["currency"] = None
        draft.pop("_catalog_currency_inferred", None)
    for item, match in zip(items, exact_matches):
        if is_manual_sample(draft, item):
            item['master_price'] = False
            continue
        user_entered_price = str(item.get("price_source") or "").casefold().startswith(
            ("user-entered", "user supplied", "user-provided"))
        if is_purchase_order and not item.get("price_override_confirmed") and not user_entered_price:
            item["unit_price"] = None
            item["price_source"] = None
        if draft.get("product_family") != "cosmetics":
            item["master_price"] = False
            continue
        if match["status"] != "matched":
            if (is_purchase_order and not user_entered_price) or item.get("master_price") is True:
                item["unit_price"] = None
                item["price_source"] = None
                item.pop("price_override_confirmed", None)
                item.pop("product_id", None)
            item["master_price"] = False
            if match["status"] == "suggested":
                suggestions = match.get("suggestions", [])
                if suggestions:
                    candidate = suggestions[0]
                    message = (
                        f"Double-check this product: {item.get('product_name') or 'item'} may be "
                        f"{candidate['product']['item_name']} ({candidate['similarity']:.0%} similarity). "
                        "Correct the product name or confirm the source before quoting."
                    )
                else:
                    message = f"Double-check this product: {item.get('product_name') or 'item'}."
                if message not in pending:
                    pending.append(message)
            draft.setdefault("missing_fields", []).append(
                f"Exact catalog product match for {item.get('product_name') or 'item'}; capacity/SKU may be needed")
            continue
        product = match["product"]
        if match.get("confirmation") and match["confirmation"] not in pending:
            pending.append(match["confirmation"])
        if not party_matches:
            if item.get("master_price") is True:
                item["unit_price"] = None
                item["price_source"] = None
                item.pop("price_override_confirmed", None)
            item["master_price"] = False
            if item.get("source") and item.get("unit_price") not in (None, ""):
                item["price_override_confirmed"] = True
                item["price_source"] = "User-provided price; counterparty is outside the local catalog price profile"
            else:
                labels = _party_labels(price_rows, party_field, product.get("id"))
                draft.setdefault("missing_fields", []).append(
                    f"Confirm a transaction-specific price for {product.get('item_name')}; local catalog price is only for {labels}")
            continue
        currency = draft.get("currency")
        price = resolve_price(product["id"], catalog, "purchase" if draft.get("document_type") == "PO" else "sale",
                              currency, stored_party_key)
        if not price:
            if is_purchase_order and not user_entered_price:
                item["unit_price"] = None
                item["price_source"] = None
                item.pop("price_override_confirmed", None)
            item["master_price"] = False
            draft.setdefault("missing_fields", []).append(
                f"Verified {currency or 'currency'} catalog price for {product.get('item_name')}")
            continue
        if not draft.get("currency"):
            # When an exact product/counterparty catalog lookup returns one
            # currency only, use that catalog currency instead of asking the
            # model to infer it from the order screenshot.
            draft["currency"] = price.get("currency")
            draft["_catalog_currency_inferred"] = True
        provided = item.get("unit_price")
        provided_amount = None
        try:
            if provided not in (None, ""):
                candidate_amount = Decimal(str(provided))
                if candidate_amount.is_finite() and candidate_amount > 0:
                    provided_amount = candidate_amount
        except (InvalidOperation, TypeError, ValueError):
            pass
        if is_purchase_order and not item.get("price_override_confirmed"):
            provided_amount = None
        price_differs = (provided_amount is not None and
                         provided_amount != Decimal(str(price["unit_price"])))
        if item.get("price_override_confirmed"):
            draft["conflicts"] = [c for c in draft.get("conflicts", [])
                                  if not (product.get("item_name", "") in c and "stated price differs from the verified catalog" in c)]
        if price_differs and not item.get("price_override_confirmed"):
            draft.setdefault("conflicts", []).append(
                f"{product.get('item_name')} stated price differs from the verified catalog; confirm transaction override")
        if not price_differs:
            item["product_id"] = product["id"]
            item["unit_price"] = str(price["unit_price"])
            catalog_basis = str(price.get("price_basis") or "").strip()
            catalog_basis = re.sub(r"^(?:USD|KRW|EUR|CNY)\s*(?:/\s*|PER\s+)?", "", catalog_basis, flags=re.I)
            catalog_basis = re.sub(r"^PER\s+", "", catalog_basis, flags=re.I)
            if is_purchase_order:
                item["price_basis"] = catalog_basis or item.get("unit")
            elif not item.get("price_basis"):
                item["price_basis"] = catalog_basis or item.get("unit")
            source_row = price.get("source_row")
            item["price_source"] = ("Verified catalog price; source row " + str(source_row)
                                    if source_row is not None else "Verified catalog price")
            item["master_price"] = True
        elif item.get("price_override_confirmed"):
            item["price_source"] = "User-confirmed transaction-specific override"
            item["master_price"] = False
