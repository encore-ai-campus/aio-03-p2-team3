"""첨부 PI → CI 변환 어댑터(kekorea-port 5절 D).

원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py — 복사본.
바꾼 것은 import 경로(`Quotation_KEKOREA.agent...` → `app.trade...`)와 마지막 가격 적용 함수 이름
(`apply_verified_eclado_prices` → `apply_verified_catalog_prices`, 이식 규칙: 회사 고유 값 금지)뿐이다.
계약 15.4절 일정 대응으로 2절(A)·3절(B)이 원본 복사본을 먼저 넣었고, 5절(D)이 그 위에서 CI·PL
흐름을 확정했다. 계약 15.2절: 이식본은 `prepare_ci_import`을 항상 `has_attachments=True`로 부른다
(첨부 파일 읽기는 범위 밖이라 CI 변환의 원문 근거는 메일 본문에 인용된 PI 내용이다).
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

_PAYMENT = re.compile(r'\b(?:payment|bank|beneficiary|swift|iban|bic|a/c|account\s*(?:number|no\.?)|remittance|t[./]?t)\b|은행|계좌|결제|송금|银行|銀行|付款|收款', re.I)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py is_pi_import
def is_pi_import(draft):
    return draft.get('document_type') == 'CI' and draft.get('_ci_from_pi') is True


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py is_ci_conversion_request
def is_ci_conversion_request(prompt):
    text = str(prompt or '')
    pi = r'(?:\bPI\b|pro\s*forma\s+invoice)'
    ci = r'(?:\bCI\b|commercial\s+invoice)'
    return bool(re.search(r'(?:PI|proforma\s+invoice|pro\s*forma\s+invoice).{0,70}?(?:CI|commercial\s+invoice|상업송장)\s*(?:로|를|을)?\s*(?:작성|만들|생성|변환)', text, re.I)
                or re.search(rf'\b(?:convert|turn|use)\b.{{0,35}}?{pi}.{{0,45}}?\b(?:to|into|as|create|make|prepare)\b.{{0,15}}?{ci}', text, re.I)
                or re.search(rf'\b(?:create|make|prepare|generate|draft)\b.{{0,15}}?{ci}\s+(?:from|using|based\s+on)\b.{{0,35}}?{pi}', text, re.I))


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py _zero_price_evidence
def _zero_price_evidence(item):
    if str(item.get('price_source') or '').startswith('User-entered'):
        return True
    source = str(item.get('source') or '')
    return bool(re.search(r'\b(?:foc|free\s+of\s+charge|no\s+charge)\b|무료|무상', source, re.I)
                or re.search(r'(?:\b(?:USD|KRW|EUR|CNY|price|rate)|US\$|\$|₩|€)\s*[:=]?\s*0(?:\.0+)?(?![\d.])', source, re.I)
                or re.search(r'(?<![\d.])0\.0+(?![\d.]|\s*(?:pcs|ml|g|kg)\b)', source, re.I))


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py _amount
def _amount(value):
    try:
        text = str(value).strip()
        if ',' in text and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            return None
        amount = Decimal(text.replace(',', ''))
        return amount if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py _has_discount_evidence
def _has_discount_evidence(item):
    source = str(item.get('source') or '')
    return bool(re.search(r'\b(?:discount|discounted|disc)\b|%|할인', source, re.I))


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py _resolved_import_notice
def _resolved_import_notice(entry, draft):
    notice = str(entry).casefold()
    buyer = draft.get('buyer') or {}
    seller = draft.get('seller') or {}
    if ('buyer' in notice and 'legal name' in notice and 'address' in notice
            and buyer.get('legal_name') and buyer.get('address')):
        return True
    if ('seller' in notice and 'legal name' in notice and 'address' in notice
            and seller.get('legal_name') and seller.get('address')):
        return True
    if any(label in notice for label in ('commercial invoice number', 'invoice number', 'document number')):
        return bool(draft.get('document_number'))
    if 'shipment reference' in notice:
        return bool(draft.get('shipment_reference'))
    if 'country of origin' in notice:
        return bool(draft.get('country_of_origin'))
    return False


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py _sanitize_import
def _sanitize_import(draft):
    draft['payment_terms'] = 'N/A'
    for key in ('bank_details', 'bank_information', 'payment_details', 'payment_information', 'bank_account', 'swift', 'account_number'):
        draft.pop(key, None)
    if _PAYMENT.search(str(draft.get('remarks') or '')):
        draft['remarks'] = 'N/A'
    def notices(entries):
        kept = []
        for entry in entries:
            if _PAYMENT.search(str(entry)):
                if re.search(r'currency|통화', str(entry), re.I):
                    entry = 'Currency conflict in source PI; confirm the transaction currency independently of banking information'
                else:
                    continue
            match = re.fullmatch(r'Item (\d+) (free quantity|discount percent|shipped quantity) was not found in its source quote; confirm the value', str(entry), re.I)
            if match:
                index = int(match[1]) - 1
                if 0 <= index < len(draft.get('items', [])):
                    item = draft['items'][index]
                    field = match[2].lower().replace(' ', '_')
                    value = _amount(item.get(field))
                    if field in ('free_quantity', 'discount_percent') and value == 0:
                        continue  # Omitted FOC/discount columns mean no addition.
                    paid = _amount(item.get('paid_quantity', item.get('quantity')))
                    free = _amount(item.get('free_quantity'))
                    if field == 'shipped_quantity' and paid is not None and free is not None and value == paid + free:
                        continue  # Derived shipping total need not be printed twice.
            if entry not in kept:
                kept.append(entry)
        return kept
    for item in draft.get('items', []):
        if item.get('discount_percent') in (None, '') and item.get('source') and not _has_discount_evidence(item):
            item['discount_percent'] = '0'
    draft['missing_fields'] = notices(draft.get('missing_fields', []))
    draft['missing_fields'] = [entry for entry in draft['missing_fields']
                               if not _resolved_import_notice(entry, draft)]
    draft['conflicts'] = notices(draft.get('conflicts', []))
    for item in draft.get('items', []):
        amount = _amount(item.get('unit_price'))
        if item.get('source') and amount is not None and (amount > 0 or _zero_price_evidence(item)):
            item.update(price_override_confirmed=True, master_price=False, _pi_import_price=True)
            if not item.get('price_source') or not str(item['price_source']).startswith('User-'):
                item['price_source'] = 'Attached PI transaction price; verify against source'
            if not item.get('price_basis') and item.get('unit'):
                item['price_basis'] = item['unit']
        else:
            item.pop('_pi_import_price', None)
    return draft


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py prepare_ci_import
def prepare_ci_import(draft, *, requested_type, has_attachments):
    source = str(draft.get('source_document_type') or draft.get('document_type') or '').upper()
    if requested_type != 'CI' or not has_attachments or source != 'PI':
        return draft
    draft.update(document_type='CI', source_document_type='PI', _ci_from_pi=True)
    return _sanitize_import(draft)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py apply_document_prices
def apply_document_prices(draft, catalog=None):
    if draft.get('document_type') in {'CI', 'PL'}:
        from app.trade.pricing import apply_catalog_product_matches
        apply_catalog_product_matches(draft, catalog)
        pi_required = 'CI must be created from an attached PI to use its transaction prices'
        draft['missing_fields'] = [entry for entry in draft.get('missing_fields', [])
                                   if entry != pi_required]
        if is_pi_import(draft):
            return _sanitize_import(draft)
        if draft.get('document_type') == 'CI':
            draft.setdefault('missing_fields', []).append(pi_required)
        return draft
    if is_pi_import(draft):
        return _sanitize_import(draft)
    from app.trade.pricing import apply_verified_catalog_prices
    return apply_verified_catalog_prices(draft, catalog)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py pi_source_zero_price
def pi_source_zero_price(draft, item):
    return is_pi_import(draft) and item.get('_pi_import_price') is True and bool(item.get('source')) and _amount(item.get('unit_price')) == 0 and _zero_price_evidence(item)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py ci_import_issues
def ci_import_issues(result):
    if result.get('document_type') == 'CI' and not is_pi_import(result):
        return ['CI must be created from an attached PI to use its transaction prices']
    if not is_pi_import(result):
        return []
    issues = []
    quantum = Decimal('1') if result.get('currency') == 'KRW' else Decimal('0.01')
    def compare(original, calculated, label):
        if original in (None, ''):
            return
        source, computed = _amount(original), _amount(calculated)
        if source is None or computed is None or source.quantize(quantum, rounding=ROUND_HALF_UP) != computed.quantize(quantum, rounding=ROUND_HALF_UP):
            issues.append(f'PI import {label}: source amount differs from the calculated amount; review the source and extracted values')
    compare(result.get('source_total'), result.get('total'), 'total')
    for index, item in enumerate(result.get('items', []), 1):
        compare(item.get('source_line_total'), item.get('line_total'), f'item {index} amount')
    for issue in result.get('blocking_issues', []):
        if issue.startswith(('Valid ', 'Shipped quantity ', 'Promotion ', 'Cosmetics price ', 'Price basis ', 'Price source ', 'Confirm discount ')):
            issues.append('PI import: ' + issue)
        elif re.search(r'Item \d+.*(?:source quote|exact quote)', issue, re.I):
            issues.append('PI import source evidence: ' + issue)
    return issues


# 원본: reference/kekorea/Quotation_KEKOREA/agent/ci_import.py ci_render_data
def ci_render_data(result):
    if not is_pi_import(result):
        return result
    result = _sanitize_import(deepcopy(result))
    for item in result.get('items', []):
        free = _amount(item.get('free_quantity'))
        if free is not None and free > 0:
            # Existing CI PDF appends FOC separately. The shipping total remains
            # untouched, and the existing Excel renderer already separates FOC.
            item['display_quantity'] = item.get('paid_quantity')
    return result
