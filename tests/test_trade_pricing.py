"""가격 출처·카탈로그 오류 처리 pytest(원본 tests/test_po_partial_catalog.py·test_supabase_catalog.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_po_partial_catalog.py,
      reference/kekorea/Quotation_KEKOREA/tests/test_supabase_catalog.py
- Supabase 카탈로그 불러오기(load_supabase_catalog)는 계약 15.4절이 없애고
  `build_trade_catalog`(price_list_items 무역 행 → seed 구조)로 바꿨다. 원본의 오류 처리 시험
  (값 검증·실패 시 단가 노출 금지)을 이 함수로 옮겼다.
- 계약 15.4절 일반화: PO 가격 적용은 문서 seller 이름 키와 가격 행 party_key 일치(없으면 공통 행)로
  판정하고, PO 통화 KRW 강제를 없앴다(문서에 명시된 통화 우선, 없으면 매입 행 통화가 하나뿐일 때 추론).
  이 부분은 원본과 달라진 동작이므로 기대값을 새 규칙에 맞춰 두고 PR에 차이로 적는다.
- 거래처·상품 이름은 가상 값이다.
"""
import pytest

from app.trade.common.pricing import (
    apply_verified_catalog_prices,
    build_trade_catalog,
    is_supplier_alias,
)
from app.trade.common.trade_documents import validate_and_calculate


def partial_order():
    # 가상 단가만 쓴다: 매칭된 24행 + 프로모션 행 하나(모호)로 원본 시나리오를 재현한다.
    products = [dict(id=f'p{i}', item_name=f'Image product {i}', capacity='100ml')
                for i in range(24)]
    products += [dict(id=f't{i}', item_name='Test Whitening Toner', capacity=capacity)
                 for i, capacity in enumerate(('150ml', None))]
    catalog = dict(products=products, purchase_prices=[
        dict(product_id=p['id'], supplier_key='ACME_SUPPLIER', currency='KRW',
             unit_price='1000', source_row=i + 1) for i, p in enumerate(products)])
    draft = dict(document_type='PO', product_family='cosmetics', currency=None,
                 seller=dict(legal_name='Acme Supplier Co. Ltd'), items=[
                     dict(product_name=p['item_name'], capacity=p['capacity'],
                          quantity='10', unit_price=None) for p in products[:24]])
    draft['items'].append(dict(product_name='Test Whitening Toner', capacity=None,
                               quantity=None, unit_price=None, promotion='Buy 3, get 1 free'))
    return draft, catalog


def test_ambiguous_promotion_row_keeps_24_verified_prices():
    draft, catalog = partial_order()
    original_items = [dict(item) for item in draft['items']]
    apply_verified_catalog_prices(draft, catalog)
    assert draft['currency'] == 'KRW'  # 매입 행 통화가 하나뿐이라 추론된 값
    assert draft['_catalog_currency_inferred'] is True
    assert [row.get('unit_price') for row in draft['items'][:24]] == ['1000'] * 24
    assert all(row['master_price'] for row in draft['items'][:24])
    assert draft['pending_confirmations'] == []
    toner = draft['items'][-1]
    assert toner['unit_price'] is None
    assert toner['quantity'] is None
    assert not toner['master_price']
    assert any('Exact catalog product match for Test Whitening Toner' in issue
               for issue in draft['missing_fields'])
    assert [(r['product_name'], r['capacity'], r['quantity']) for r in draft['items']] == \
           [(r['product_name'], r['capacity'], r['quantity']) for r in original_items]
    apply_verified_catalog_prices(draft, catalog)
    assert draft['pending_confirmations'] == []


def test_po_prices_require_matching_party_key_or_common_rows():
    """계약 15.4절: PO라도 seller 이름 키가 가격 행 party_key와 다르면(공통 행도 없으면) 적용하지 않는다."""
    for supplier, currency in (('Other supplier', None), ('다른 공급처', None), (None, None)):
        draft, catalog = partial_order()
        draft['seller']['legal_name'] = supplier
        draft['currency'] = currency
        apply_verified_catalog_prices(draft, catalog)
        assert all(row.get('unit_price') is None for row in draft['items']), (supplier, currency)
        assert any('transaction-specific price for Image product 0' in issue
                   for issue in draft['missing_fields'])
        assert draft['currency'] == currency
    # seller는 맞지만 문서에 명시된 통화의 매입 행이 없으면 그 통화로 확인을 요청한다(KRW 강제 없음).
    draft, catalog = partial_order()
    draft['currency'] = 'USD'
    apply_verified_catalog_prices(draft, catalog)
    assert all(row.get('unit_price') is None for row in draft['items'])
    assert any('Verified USD catalog price for Image product' in issue
               for issue in draft['missing_fields'])
    assert draft['currency'] == 'USD'


def test_common_purchase_rows_apply_to_any_seller():
    """party_key가 빈 문자열인 공통 가격 행은 모든 거래처에 적용된다(계약 15.4절)."""
    draft, catalog = partial_order()
    for row in catalog['purchase_prices']:
        row['supplier_key'] = ''
    draft['seller']['legal_name'] = None
    apply_verified_catalog_prices(draft, catalog)
    assert [row.get('unit_price') for row in draft['items'][:24]] == ['1000'] * 24
    assert draft['currency'] == 'KRW'


def test_no_exact_matches_do_not_infer_price():
    draft, catalog = partial_order()
    draft['product_family'] = 'other'
    draft['items'] = [dict(product_name='Unrelated product', capacity='10ml',
                           quantity='1', unit_price='5', source='USD 5 each')]
    apply_verified_catalog_prices(draft, catalog)
    assert draft['pending_confirmations'] == []
    assert draft['product_family'] == 'cosmetics'
    assert draft['items'][0]['unit_price'] is None
    assert draft['currency'] is None  # 가격을 찾하지 못했으므로 통화도 정하지 않는다
    assert any('Exact catalog product match for Unrelated product' in issue
               for issue in draft['missing_fields'])


# --- 원본 test_supabase_catalog.py 이식(Supabase 대신 사용자 단가표) ---

def single_product_catalog(role='purchase', party='ACME_SUPPLIER', currency='KRW', price='1000'):
    price_row = {('supplier_key' if role == 'purchase' else 'buyer_key'): party}
    return {'products': [{'id': 'p1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
            'purchase_prices': [], 'buyer_prices': []}, price_row


def test_supplier_name_variants_share_the_verified_purchase_profile():
    catalog = {'products': [{'id': 'p1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
               'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ACME_SUPPLIER',
                                    'currency': 'KRW', 'unit_price': '1000', 'source_row': 1}]}
    aliases = ('acme supplier', 'ACME SUPPLIER', 'Acme Supplier Co., Ltd.',
               'a C m e Supplier Co., Ltd.', 'ＡＣＭＥ　ＳＵＰＰＬＩＥＲ')
    for name in aliases:
        draft = {'document_type': 'PO', 'product_family': 'other', 'currency': None,
                 'seller': {'legal_name': name},
                 'items': [{'product_name': 'Test Cream', 'capacity': '50 ml', 'unit': 'PCS'}]}
        apply_verified_catalog_prices(draft, catalog)
        assert draft['currency'] == 'KRW'
        assert draft['items'][0].get('unit_price') == '1000'
        assert draft['items'][0].get('price_basis') == 'PCS'
        assert draft['items'][0]['master_price']
        assert draft['seller']['legal_name'] == name
        assert draft.get('pending_confirmations') == []


def test_recognized_supplier_loads_matching_rows_even_if_one_product_is_unmatched():
    catalog = {'products': [{'id': 'p1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
               'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ACME_SUPPLIER',
                                    'currency': 'KRW', 'unit_price': '1000', 'source_row': 1}]}
    draft = {'document_type': 'PO', 'product_family': 'other', 'currency': None,
             'seller': {'legal_name': 'Acme Supplier Co. Ltd'},
             'items': [{'product_name': 'Test Cream', 'capacity': '50 ml'},
                       {'product_name': 'Unconfirmed Product', 'capacity': '10 ml'}]}
    apply_verified_catalog_prices(draft, catalog)
    assert draft['product_family'] == 'cosmetics'
    assert draft['currency'] == 'KRW'
    assert draft['items'][0].get('unit_price') == '1000'
    assert draft['items'][1].get('unit_price') is None
    assert any('Unconfirmed Product' in entry for entry in draft['missing_fields'])


def test_po_with_issuer_named_seller_needs_price_rows_for_that_seller():
    """원본은 PO가 항상 매입가를 썼다. 계약 15.4절 일반화 뒤에는 발행사가 seller로 남면 가격 행
    party_key가 맞지 않아 적용하지 않고, 공통 행이 있으면 적용한다."""
    catalog = {'products': [{'id': 'p1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
               'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ACME_SUPPLIER',
                                    'currency': 'KRW', 'unit_price': '1000', 'source_row': 1}]}
    base = {'document_type': 'PO', 'product_family': 'cosmetics', 'currency': 'USD',
            'buyer': {'legal_name': 'Testworks Trading Co. Ltd', 'address': 'Buyer address'},
            'missing_fields': ['PO buyer legal name and address',
                               'PO supplier legal name and address'],
            'items': [{'product_name': 'Test Cream', 'capacity': '50 ml', 'unit': 'PCS',
                       'unit_price': '10.25', 'price_basis': 'USD/PCS',
                       'source': 'USD 10.25 per PCS'}]}
    draft = {**base, 'seller': {'legal_name': 'Testworks Trading Co. Ltd', 'address': 'Supplier address'}}
    apply_verified_catalog_prices(draft, catalog)
    assert draft['currency'] == 'USD'
    assert draft['items'][0].get('unit_price') is None
    assert draft['items'][0]['master_price'] is False
    assert not draft.get('conflicts')

    common = {**catalog, 'purchase_prices': [dict(catalog['purchase_prices'][0], supplier_key='')]}
    # 통화가 명시된 USD면 그 통화의 행만 찾는다(없으므로 확인 요청).
    apply_verified_catalog_prices(draft, common)
    assert draft['currency'] == 'USD'
    assert draft['items'][0]['unit_price'] is None
    assert any('Verified USD catalog price for Test Cream' in issue
               for issue in draft['missing_fields'])
    # 통화가 없으면 공통 행의 통화가 하나뿐이라 그 통화로 정한다(계약 15.4절).
    draft['currency'] = None
    apply_verified_catalog_prices(draft, common)
    assert draft['items'][0]['unit_price'] == '1000'
    assert draft['items'][0]['price_basis'] == 'PCS'
    assert draft['items'][0]['price_source'] == 'Verified catalog price; source row 1'
    assert draft['items'][0]['master_price']
    assert draft['currency'] == 'KRW'
    assert draft['missing_fields'] == []
    assert draft.get('pending_confirmations') == []


def test_loaded_price_list_feeds_the_exact_match_price_resolver():
    catalog = {
        'products': [{'id': 'product-1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
        'purchase_prices': [],
        'buyer_prices': [{'product_id': 'product-1', 'buyer_key': 'ACME_BUYER',
                          'currency': 'USD', 'unit_price': '10.25', 'source_row': 7}],
    }
    draft = {'document_type': 'PI', 'product_family': 'cosmetics', 'currency': 'USD',
             'buyer': {'legal_name': 'Acme Buyer Pte Ltd'},
             'items': [{'product_name': 'Test Cream', 'capacity': '50 ml',
                        'unit_price': None, 'source': None}]}
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0]['unit_price'] == '10.25'
    assert draft['items'][0]['master_price'] is True


def test_zero_quantity_po_uses_purchase_prices_without_mixing_sale_currency():
    catalog = {'products': [{'id': 'p1', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
               'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ACME_SUPPLIER',
                                    'currency': 'KRW', 'unit_price': '1000', 'source_row': 1}],
               'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'ACME_BUYER', 'currency': 'USD',
                                 'unit_price': '10', 'source_row': 1}]}
    draft = {'document_type': 'PO', 'product_family': 'cosmetics', 'currency': None,
             'seller': {'legal_name': 'Acme Supplier'},
             'buyer': {'legal_name': 'Testworks Trading Co. Ltd'},
             'items': [{'product_name': 'Test Cream', 'capacity': '50 ml', 'quantity': str(qty),
                        'paid_quantity': str(qty), 'shipped_quantity': str(qty), 'unit': 'PCS',
                        'price_basis': 'USD/PCS', 'discount_percent': '0'} for qty in (0, 5)]}
    apply_verified_catalog_prices(draft, catalog)
    result = validate_and_calculate(draft, issuer_key='testworkstrading')
    assert result['currency'] == 'KRW'
    assert result['total'] == '5000'
    assert result['items'][0]['line_total'] == '0'
    assert all(item['master_price'] and item['unit_price'] == '1000' for item in result['items'])
    assert all(item['price_basis'] == 'PCS' for item in result['items'])
    assert not any('number required' in issue for issue in result['blocking_issues'])
    # 통화를 USD로 명시하면 USD 매입 행만 찾는다(원본의 KRW 되돌림과 다른 계약 15.4절 동작).
    draft['currency'] = 'USD'
    for item in draft['items']:
        item['unit_price'] = '10'
        item['source'] = 'USD 10 per PCS'
    apply_verified_catalog_prices(draft, catalog)
    assert draft['currency'] == 'USD'
    assert all(item['unit_price'] is None for item in draft['items'])
    assert any('Verified USD catalog price for Test Cream' in issue
               for issue in draft['missing_fields'])


def test_is_supplier_alias_recognizes_only_configured_aliases():
    assert is_supplier_alias('Acme Supplier Co. LTD', ['acme supplier', '에크미 공급'])
    assert is_supplier_alias('주식회사 에크미', ['에크미'])
    assert not is_supplier_alias('Other Supplier Ltd', ['acme supplier'])
    assert not is_supplier_alias('Acme Supplier', [])
    assert not is_supplier_alias(None, ['acme supplier'])


# --- 원본 test_supabase_catalog.py의 오류 처리를 build_trade_catalog로 옮긴 것 ---

def test_build_trade_catalog_rejects_bad_rows_without_echoing_prices():
    base = {'id': 1, 'item_name': 'Test Cream', 'role': 'purchase', 'currency': 'KRW',
            'unit_price_text': '8000', 'party_key': 'ACME_SUPPLIER'}
    bad_rows = [
        {**base, 'role': 'wholesale'},
        {**base, 'currency': 'WON2'},
        {**base, 'currency': ''},
        {**base, 'unit_price_text': 'not-a-price'},
        {**base, 'unit_price_text': '-5'},
        {**base, 'unit_price_text': 'NaN'},
        {**base, 'item_name': '  '},
    ]
    for row in bad_rows:
        with pytest.raises(ValueError) as ctx:
            build_trade_catalog([row])
        assert '8000' not in str(ctx.value)  # 단가 값은 오류 메시지에 노출하지 않는다


def test_build_trade_catalog_dedupes_products_and_keeps_first_nonempty_values():
    catalog = build_trade_catalog([
        {'id': 3, 'item_name': 'Test Cream', 'role': 'sale', 'currency': 'EUR',
         'unit_price_text': '9', 'party_key': 'ACME_BUYER', 'capacity': '', 'product_code': ''},
        {'id': 1, 'item_name': 'Test Cream', 'role': 'purchase', 'currency': 'KRW',
         'unit_price_text': '1,000', 'party_key': 'ACME_SUPPLIER', 'capacity': '50ml',
         'product_code': 'T-1', 'price_basis': 'per PCS'},
        {'id': 2, 'item_name': 'Test Cream', 'role': 'sale', 'currency': 'USD',
         'unit_price_text': '10.25', 'party_key': 'ACME_BUYER'},
    ])
    assert len(catalog['products']) == 1
    product = catalog['products'][0]
    assert product['id'] == 1  # 그 품목 행들 중 가장 작은 행 id
    assert product['capacity'] == '50ml'
    assert product['source_code'] == 'T-1'
    assert len(catalog['purchase_prices']) == 1
    assert catalog['purchase_prices'][0]['unit_price'] == '1,000'
    assert {row['currency'] for row in catalog['buyer_prices']} == {'USD', 'EUR'}
    # 매칭이 이름으로 product를 고르므로 중복 product가 없으면 ambiguous되지 않는다.
    from app.trade.common.pricing import match_catalog_product
    assert match_catalog_product('Test Cream', '50ml', catalog['products'])['status'] == 'matched'
