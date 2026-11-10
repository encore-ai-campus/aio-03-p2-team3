"""Transaction-only PI samples; no catalog or database writes."""
import re
import unicodedata


def has_sample_keyword(value):
    text = unicodedata.normalize('NFKC', str(value or ''))
    return '샘플' in text or bool(re.search(r'(?<![a-z0-9])sample(?![a-z0-9])', text, re.I))


def is_manual_sample(draft, item):
    return draft.get('document_type') == 'PI' and item.get('is_sample') is True


def new_sample():
    item = {}
    update_sample(item, name=None, capacity='', quantity=None, unit='PCS', price=None)
    return item


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


def edit_sample_rows(draft, page):
    """Use existing review-state storage so sidebar/new-order behavior is shared."""
    if draft.get('document_type') != 'PI':
        return set()
    originals = [i for i in draft.get('items', []) if is_manual_sample(draft, i)]
    if not draft.get('_samples_requested') and not originals:
        return set()
    import streamlit as st
    values = st.session_state.setdefault(f'review_values_{page}', {})
    count = values.setdefault('_sample_count', len(originals) or 1)
    st.markdown('### 샘플 수동 입력')
    st.caption('품명·용량·수량·단가를 입력하세요. 단가 0도 가능합니다. 입력한 수량과 금액은 인보이스 합계에 포함됩니다.')
    if st.button('샘플 행 추가', key=f'pi_sample_add_{page}'):
        count += 1
        values['_sample_count'] = count
    samples = []
    for index in range(count):
        item = dict(originals[index]) if index < len(originals) else new_sample()
        prefix = f'review_missing_{page}_sample_{index}_'
        included_key = prefix + 'included'
        if included_key not in st.session_state:
            st.session_state[included_key] = values.get(included_key, True)
        included = st.checkbox(f'Sample {index + 1}: include in invoice', key=included_key)
        values[included_key] = included
        if not included:
            continue
        fields = (('product_name', 'product name'), ('capacity', 'capacity'),
                  ('quantity', 'quantity'), ('unit', 'unit'), ('unit_price', 'unit price'))
        entered = {}
        columns = st.columns(2)
        for column, (field, label) in enumerate(fields):
            key = prefix + field
            if key not in st.session_state:
                initial = item.get(field)
                st.session_state[key] = values.get(key, '' if initial is None else str(initial))
            entered[field] = columns[column % 2].text_input(f'Sample {index + 1}: {label}', key=key)
            values[key] = entered[field]
        update_sample(item, name=entered['product_name'], capacity=entered['capacity'],
                      quantity=entered['quantity'], unit=entered['unit'], price=entered['unit_price'])
        samples.append(item)
    regular = [i for i in draft.get('items', []) if not is_manual_sample(draft, i)]
    draft['items'] = regular + samples
    return {('items', i, key) for i in range(len(regular), len(draft['items']))
            for key in ('product_name', 'unit', 'quantity', 'unit_price', 'discount_percent')}
