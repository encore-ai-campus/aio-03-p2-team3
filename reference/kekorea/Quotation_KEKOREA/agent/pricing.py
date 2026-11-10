"""Read the locally prepared private ECLADO price seed without exposing prices in logs."""
import json
from pathlib import Path
import re
import unicodedata
from decimal import Decimal, InvalidOperation
import json as json_module
import urllib.error
import urllib.parse
import urllib.request
from Quotation_KEKOREA.agent.product_matching import match_product


def load_local_seed(seed_path=None):
    path = Path(seed_path) if seed_path else Path(__file__).resolve().parents[1] / "private" / "eclado" / "002_eclado_catalog_seed.sql"
    if not path.exists():
        return {"products": [], "purchase_prices": [], "buyer_prices": []}
    sql = path.read_text(encoding="utf-8")
    match = re.search(r"\$kekorea_seed\$(.*?)\$kekorea_seed\$", sql, re.S)
    if not match:
        raise ValueError("Local catalog seed is malformed")
    return json.loads(match.group(1))


def load_local_catalog(seed_path=None):
    return load_local_seed(seed_path).get("products", [])


def load_supabase_catalog(env, *, opener=urllib.request.urlopen, timeout=20):
    """Load one consistent catalog snapshot using a server-only Supabase secret key."""
    base_url = str(env.get("SUPABASE_URL", "")).rstrip("/")
    secret_key = str(env.get("SUPABASE_SECRET_KEY", ""))
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.query or parsed.fragment:
        raise ValueError("SUPABASE_URL must be the HTTPS URL of this Supabase project")
    if not secret_key:
        raise ValueError("SUPABASE_SECRET_KEY is not configured")

    def get_rows(table, params):
        query = urllib.parse.urlencode(params)
        url = f"{base_url}/rest/v1/{table}?{query}"
        request = urllib.request.Request(url, headers={"apikey": secret_key, "Accept": "application/json"}, method="GET")
        try:
            with opener(request, timeout=timeout) as response:
                rows = json_module.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Supabase catalog request failed (HTTP {exc.code}); check the server key, API exposure, and table permissions") from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("Supabase could not be reached; check the project URL and network") from None
        except (UnicodeDecodeError, json_module.JSONDecodeError):
            raise RuntimeError("Supabase returned an invalid catalog response") from None
        if not isinstance(rows, list):
            raise RuntimeError("Supabase returned an unexpected catalog response")
        return rows

    imports = get_rows("kekorea_catalog_imports", [
        ("select", "id,source_label,imported_at,payload_sha256"),
        ("order", "imported_at.desc"), ("limit", "1")])
    if not imports:
        raise RuntimeError("No ECLADO catalog import was found in Supabase")
    import_id = imports[0].get("id")
    if not import_id:
        raise RuntimeError("The latest Supabase catalog import has no ID")

    products = get_rows("kekorea_products", [
        ("select", "id,brand,kind,source_code,item_name,capacity,group_name,metadata"),
        ("brand", "eq.ECLADO"), ("limit", "1000")])
    prices_query = [("select", "id,import_id,product_id,supplier_key,currency,unit_price,price_basis,source_row,source_column,effective_from,effective_to"),
                    ("import_id", f"eq.{import_id}"), ("limit", "1000")]
    purchase_prices = get_rows("kekorea_purchase_prices", prices_query)
    buyer_query = [("select", "id,import_id,product_id,buyer_key,currency,unit_price,price_basis,reference_discount_percent,reference_discounted_price,source_row,source_column,effective_from,effective_to"),
                   ("import_id", f"eq.{import_id}"), ("limit", "1000")]
    buyer_prices = get_rows("kekorea_buyer_prices", buyer_query)

    product_ids = {row.get("id") for row in products}
    if not product_ids:
        raise RuntimeError("No ECLADO products were found in Supabase")
    for table, rows in (("purchase", purchase_prices), ("buyer", buyer_prices)):
        if not rows:
            raise RuntimeError(f"The latest Supabase import has no {table} prices")
        for row in rows:
            if row.get("import_id") != import_id or row.get("product_id") not in product_ids:
                raise RuntimeError(f"Supabase {table} prices do not match the selected catalog import")
            try:
                amount = Decimal(str(row.get("unit_price")))
            except (InvalidOperation, TypeError, ValueError):
                raise RuntimeError(f"Supabase {table} catalog contains an invalid price") from None
            if not amount.is_finite() or amount < 0:
                raise RuntimeError(f"Supabase {table} catalog contains an invalid price")

    return {"import": imports[0], "products": products,
            "purchase_prices": purchase_prices, "buyer_prices": buyer_prices}


def match_eclado_product(name, capacity=None, products=None, product_code=None):
    """Resolve a complete catalog name, verified SKU and equivalent size notation."""
    products = products if products is not None else load_local_catalog()
    return match_product(name, capacity, products, product_code)


def resolve_price(product_id, prices=None, role="sale", currency=None, party_key=None):
    """Resolve a locally seeded price only on exact product, role and currency."""
    if prices is None:
        prices = load_local_seed()
    table = "buyer_prices" if role == "sale" else "purchase_prices"
    party_field = "buyer_key" if role == "sale" else "supplier_key"
    rows = [p for p in prices.get(table, []) if p.get("product_id") == product_id and
            (currency is None or p.get("currency") == currency) and
            (party_key is None or str(p.get(party_field) or "").upper() == party_key.upper())]
    if len(rows) != 1:
        return None
    return rows[0] if len(rows) == 1 else None


def is_eclado_supplier(name):
    """Recognize the supplied ECLADO brand aliases without rewriting the legal name."""
    normalized = unicodedata.normalize("NFKC", str(name or "")).casefold()
    key = re.sub(r"[\W_]+", "", normalized)
    return any(alias in key for alias in ("eclado", "에끌라도", "에끌라두"))


def apply_catalog_product_matches(draft, seed=None):
    """Attach confident ECLADO product identities without changing document prices."""
    from Quotation_KEKOREA.agent.samples import is_manual_sample
    seed = seed if seed is not None else load_local_seed()
    products = seed.get("products", [])
    product_ids = {product.get("id") for product in products}
    draft["missing_fields"] = [
        entry for entry in draft.get("missing_fields", [])
        if not (str(entry).startswith("Exact ECLADO product match for ")
                and str(entry).endswith("; capacity/SKU may be needed"))
    ]
    pending = draft.setdefault("pending_confirmations", [])
    pending[:] = [entry for entry in pending if not str(entry).startswith(
        ("Confirm product annotation for ", "Double-check this product:"))]

    items = draft.get("items", [])
    matches = [match_eclado_product(item.get("product_name"), item.get("capacity"), products,
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
            message = (f"Double-check this product: {name} has no unique ECLADO catalog match. "
                       "Confirm the source or keep the manually entered name.")
        if message not in pending:
            pending.append(message)
        draft.setdefault("missing_fields", []).append(
            f"Exact ECLADO product match for {name}; capacity/SKU may be needed")
    return draft


def apply_verified_eclado_prices(draft, seed=None):
    """Replace ECLADO candidate price with exact catalog price or mark the uncertainty."""
    if draft.get("document_type") in {"CI", "PL"}:
        return apply_catalog_product_matches(draft, seed)
    from Quotation_KEKOREA.agent.samples import is_manual_sample
    is_purchase_order = draft.get("document_type") == "PO"
    # Recompute catalog-owned warnings after the user completes buyer/product/currency fields.
    draft["missing_fields"] = [entry for entry in draft.get("missing_fields", []) if not (
        (str(entry).startswith("Exact ECLADO product match for ") and str(entry).endswith("; capacity/SKU may be needed"))
        or (str(entry).startswith("Confirm a transaction-specific price for ") and "; local catalog price is only for " in str(entry))
        or re.fullmatch(r"Verified \S+ catalog price for .+", str(entry))
        or (is_purchase_order and "currency" in str(entry).casefold()))]
    if is_purchase_order:
        buyer = draft.get("buyer") or {}
        seller = draft.get("seller") or {}
        draft["missing_fields"] = [
            entry for entry in draft["missing_fields"]
            if not (
                (str(entry) == "PO buyer legal name and address"
                 and buyer.get("legal_name") and buyer.get("address"))
                or (str(entry) == "ECLADO supplier legal name and address"
                    and seller.get("legal_name") and seller.get("address"))
            )
        ]
        # A PO is always placed with ECLADO in KRW; source PI currency and prices
        # are customer-sale data, not the supplier purchase-price basis.
        draft["currency"] = "KRW"
        draft.pop("_catalog_currency_inferred", None)
        draft["conflicts"] = [entry for entry in draft.get("conflicts", [])
                              if "currency" not in str(entry).casefold()
                              and "stated price differs from the verified catalog" not in str(entry)]
    seed = seed if seed is not None else load_local_seed()
    products = seed.get("products", [])
    items = draft.get("items", [])
    if is_purchase_order:
        for item in items:
            basis = str(item.get("price_basis") or "").strip()
            basis = re.sub(r"^(?:USD|KRW|EUR|CNY)\s*(?:/\s*|PER\s+)?", "", basis, flags=re.I)
            basis = re.sub(r"^PER\s+", "", basis, flags=re.I)
            item["price_basis"] = basis or item.get("unit")
    # Vision extraction can label a cosmetics order as "other" when the image
    # shows products and sizes but no explicit category. An exact match of every
    # line against the ECLADO product master is stronger evidence and lets the
    # existing role/currency-specific price lookup proceed for both PI and PO.
    exact_matches = [match_eclado_product(item.get("product_name"), item.get("capacity"), products,
                                         item.get("product_code"))
                     for item in items]
    regular_matches = [match for item, match in zip(items, exact_matches) if not is_manual_sample(draft, item)]
    price_table = "purchase_prices" if draft.get("document_type") == "PO" else "buyer_prices"
    default_currency = "KRW" if draft.get("document_type") == "PO" else None
    counterparty_role = "seller" if draft.get("document_type") == "PO" else "buyer"
    counterparty_name = str((draft.get(counterparty_role) or {}).get("legal_name") or "").strip()
    counterparty = re.sub(r"\b(CO|COMPANY|PTE|LTD|LIMITED|INC|CORP|CORPORATION)\b", " ",
                          counterparty_name.upper())
    counterparty = "".join(re.findall(r"[A-Z0-9]+", counterparty))
    expected_party = "ECLADO" if draft.get("document_type") == "PO" else "DEAR GLOW"
    party_matches = (is_purchase_order or "DEARGLOW" in counterparty)
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
        "The seller was not supplied. Use the ECLADO purchase price catalog")]
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
                f"Exact ECLADO product match for {item.get('product_name') or 'item'}; capacity/SKU may be needed")
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
                draft.setdefault("missing_fields", []).append(
                    f"Confirm a transaction-specific price for {product.get('item_name')}; local catalog price is only for {expected_party}")
            continue
        currency = draft.get("currency") or default_currency
        price = resolve_price(product["id"], seed, "purchase" if draft.get("document_type") == "PO" else "sale", currency,
                              "ECLADO" if draft.get("document_type") == "PO" else "DEAR_GLOW")
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
            item["price_source"] = "Verified ECLADO catalog; source workbook row " + str(price.get("source_row"))
            item["master_price"] = True
        elif item.get("price_override_confirmed"):
            item["price_source"] = "User-confirmed transaction-specific override"
            item["master_price"] = False
