"""PI 샘플 행 pytest(원본 tests/test_pi_samples.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_pi_samples.py
- 렌더러 의존 시험(test_actual_invoice_files_include_sample_line_quantity_and_total)과
  test_zero_and_positive_sample_prices... 의 `_rows` 행 확인은 kekorea-port 4절(C 문서 출력)
  범위라 여기서는 계산 결과(total·display_quantity)만 확인한다.
- 거래처 이름은 가상 값으로 바꿨다.
"""
import copy

from app.trade.pricing import apply_verified_catalog_prices
from app.trade.promotions import apply_promotion_commands
from app.trade.samples import ensure_sample_rows, new_sample, update_sample
from app.trade.trade_documents import validate_and_calculate
from tests.test_trade_promotions import ISSUER_KEY, order


def calculate(draft):
    return validate_and_calculate(draft, issuer_key=ISSUER_KEY)


def test_keyword_opens_one_manual_row_without_duplicate_or_other_document_changes():
    for word in ('샘플', 'SAMPLE', 'sample', 'SaMpLe', 'SAMPLE도 있어', 'sample도'):
        doc = order()
        ensure_sample_rows(doc, f'Acme Buyer PI {word}')
        ensure_sample_rows(doc, f'Acme Buyer PI {word}')
        assert len(doc['items']) == 2
        assert doc['items'][-1]['is_sample']
        assert doc['items'][-1]['product_name'] is None
        assert doc['items'][-1]['quantity'] is None
        assert doc['items'][-1]['unit_price'] is None
    for dtype, prompt in (('PO', 'sample'), ('CI', '샘플'), ('PI', 'regular order')):
        doc = order(dtype)
        before = copy.deepcopy(doc)
        ensure_sample_rows(doc, prompt)
        assert doc == before


def test_regular_discount_confirmation_ignores_independent_manual_samples():
    from app.trade.review_fields import apply_review_value, missing_review_fields
    doc = order()
    doc['items'][0]['discount_percent'] = None
    doc['conflicts'] = ['Discount was mentioned without a percentage; specify a single discount rate.']
    doc['items'].append(new_sample())
    field = next(f for f in missing_review_fields(doc) if f.path == ('items', 0, 'discount_percent'))
    apply_review_value(doc, field, '10')
    assert not doc['conflicts']
    assert doc['items'][1]['discount_percent'] == '0'


def test_existing_sample_is_editable_without_creating_an_extra_row():
    doc = order()
    doc['items'].append(dict(product_name='Toner SAMPLE', quantity='5', unit_price='0'))
    ensure_sample_rows(doc, '샘플도 있어')
    assert len(doc['items']) == 2
    assert doc['items'][-1]['is_sample']


def test_zero_and_positive_sample_prices_are_included_in_quantity_and_amount():
    for price, amount in (('0', '20.00'), ('0.25', '21.25')):
        doc = order()
        doc['product_family'] = 'cosmetics'
        doc['items'][0]['price_override_confirmed'] = True
        item = new_sample()
        update_sample(item, name='Trial Toner', capacity='2ml', quantity='5', unit='PCS', price=price)
        doc['items'].append(item)
        result = calculate(doc)
        assert not result['blocking_issues'], result['blocking_issues']
        assert result['total'] == amount
        assert sum(int(i['display_quantity']) for i in result['items']) == 15
        sample_row = result['items'][-1]
        assert sample_row['product_name'] == 'Trial Toner'
        assert sample_row['quantity'] == '5'
        assert sample_row['final_unit_price'] == ('0' if price == '0' else '0.25')
        assert sample_row['line_total'] == ('0.00' if price == '0' else '1.25')


def test_catalog_never_overwrites_sample_even_when_name_matches_product():
    doc = order()
    doc.update(product_family='cosmetics', buyer={'legal_name': 'Acme Buyer Pte Ltd'})
    item = new_sample()
    update_sample(item, name='Trial Toner', capacity='2ml', quantity='5', unit='PCS', price='0')
    doc['items'] = [item]
    seed = {'products': [{'id': 'p1', 'item_name': item['product_name'], 'capacity': '2ml'}],
            'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'ACME_BUYER', 'currency': 'USD', 'unit_price': '25'}]}
    before = copy.deepcopy(seed)
    apply_verified_catalog_prices(doc, seed)
    assert item['unit_price'] == '0'
    assert not item['master_price']
    assert not any('SAMPLE' in s for s in doc['missing_fields'])
    assert seed == before


def test_invalid_or_missing_manual_values_block_sample():
    for quantity, price in ((None, None), ('-1', '0'), ('NaN', '0'), ('5', '-1'), ('5', 'Infinity')):
        doc = order()
        item = new_sample()
        update_sample(item, name='Trial Toner', capacity='', quantity=quantity, unit='PCS', price=price)
        doc['items'].append(item)
        result = calculate(doc)
        assert any(s.startswith('Sample ') for s in result['blocking_issues'])


def test_regular_item_and_other_documents_still_require_positive_prices():
    for dtype in ('PI', 'PO', 'CI'):
        doc = order(dtype)
        doc['items'][0].update(unit_price='0', is_sample=dtype != 'PI')
        result = calculate(doc)
        assert any('positive number required for unit price' in s for s in result['blocking_issues'])


def test_sample_does_not_receive_all_product_promotion():
    doc = order()
    doc['items'].append(new_sample())
    update_sample(doc['items'][-1], name='Trial Toner', capacity='', quantity='5', unit='PCS', price='0')
    apply_promotion_commands(doc, 'All products 3+1')
    assert doc['items'][0]['free_quantity'] == '3'
    assert doc['items'][1]['free_quantity'] == '0'
    assert not doc['items'][1].get('promotion')


def test_manual_product_name_remains_exactly_as_entered_and_can_be_edited():
    item = new_sample()
    for name in ('Trial Toner', 'Test Repair Cream', 'Trial Toner (2ml)', 'SAMPLE Kit A'):
        update_sample(item, name=name, capacity='2ml', quantity='5', unit='PCS', price='0')
        assert item['product_name'] == name
        assert item['is_sample']


def test_sample_does_not_weaken_regular_cosmetics_category_or_price_guards():
    seed = {'products': [{'id': 'p1', 'item_name': 'Test Toner', 'capacity': '50ml'}]}
    for with_sample in (False, True):
        doc = order()
        doc['items'][0].update(capacity='50ml', unit_price=None)
        if with_sample:
            doc['items'].append(new_sample())
        apply_verified_catalog_prices(doc, seed)
        assert doc['product_family'] == 'cosmetics'
        assert any('transaction-specific price for Test Toner' in s for s in doc['missing_fields'])
