"""거래 전용 PI 샘플 행(kekorea-port 2절 A가 추출 순서에 쓰고, 3절 B가 이어 쓴다).

원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py — 복사본.
계약 15.4절: `edit_sample_rows`는 원본 화면(Streamlit) 코드라 옮기지 않았다.
"""
import re
import unicodedata


# 원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py has_sample_keyword
def has_sample_keyword(value):
    text = unicodedata.normalize('NFKC', str(value or ''))
    return '샘플' in text or bool(re.search(r'(?<![a-z0-9])sample(?![a-z0-9])', text, re.I))


# 원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py is_manual_sample
def is_manual_sample(draft, item):
    return draft.get('document_type') == 'PI' and item.get('is_sample') is True


# 원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py new_sample
def new_sample():
    item = {}
    update_sample(item, name=None, capacity='', quantity=None, unit='PCS', price=None)
    return item


# 원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py update_sample
def update_sample(item, *, name, capacity, quantity, unit, price):
    def value(raw):
        return None if raw is None or not str(raw).strip() else str(raw).strip()
    name = value(name)
    item.update(is_sample=True, product_name=name, capacity=value(capacity),
                quantity=value(quantity), paid_quantity=value(quantity),
                shipped_quantity=value(quantity), free_quantity='0', unit=value(unit),
                unit_price=value(price), price_basis=value(unit), discount_percent='0',
                master_price=False, price_override_confirmed=True,
                price_source='User-entered PI sample value')
    # Samples have independent manual quantities/prices, never catalog identity
    # or paid-product promotional calculations.
    for key in ('promotion', 'product_id', 'product_code'):
        item.pop(key, None)
    return item


# 원본: reference/kekorea/Quotation_KEKOREA/agent/samples.py ensure_sample_rows
def ensure_sample_rows(draft, prompt):
    if draft.get('document_type') != 'PI' or not has_sample_keyword(prompt):
        return draft
    draft['_samples_requested'] = True
    found = False
    for item in draft.setdefault('items', []):
        if item.get('is_sample') is True or has_sample_keyword(item.get('product_name')):
            found = True
            update_sample(item, name=item.get('product_name'), capacity=item.get('capacity'),
                          quantity=item.get('paid_quantity') if item.get('paid_quantity') not in (None, '') else item.get('quantity'),
                          unit=item.get('unit') or 'PCS', price=item.get('unit_price'))
    if not found:
        draft['items'].append(new_sample())
    return draft
