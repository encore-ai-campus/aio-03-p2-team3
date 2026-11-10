"""상품명 매칭 pytest(원본 tests/test_product_matching.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_product_matching.py
- 실제 카탈로그 상품명·코드·거래처 이름은 가상 값으로 바꿨다(이식 규칙: 회사 고유 값 금지).
  이름·코드의 구조(용량·곱셈·SPF/PA·코드 표기)는 원본 테스트와 같게 유지했다.
- 원본의 `brand == 'ECLADO'` 진입 필터 검증은 브랜드 필터 자체를 계약 15.4절이 없앴으므로
  '브랜드 키 없이 카탈로그 전체를 찾는다' 검증으로 바꿨다.
- `match_eclado_product` → `match_catalog_product`, `apply_verified_eclado_prices` →
  `apply_verified_catalog_prices` 개명을 반영했다.
"""
import copy

from app.trade.pricing import (
    apply_catalog_product_matches,
    apply_verified_catalog_prices,
    match_catalog_product,
)


PRODUCTS = [
    dict(id='cream50', source_code='T-165', item_name='Test Repair Cream', capacity='50g'),
    dict(id='cream200', source_code='T-166-1', item_name='Test Repair Cream', capacity='200g'),
    dict(id='toner', source_code='R173A', item_name='Test Hydra Toner', capacity='150ml'),
    dict(id='serum', source_code='T-20', item_name='Test V-C Serum', capacity='100ml'),
    dict(id='ampoule', source_code='CX-1', item_name='Test Core Ampoule', capacity='5ml*6, 7ml*6'),
    dict(id='fiber', source_code='F-1', item_name='Test Fiber&Ampoule System', capacity='(1g + 10ml)*6'),
    dict(id='gold', source_code='G-1', item_name='Test Lift Pack Gold', capacity='3gx10,100ml'),
    dict(id='double', source_code='D-1', item_name='Test Core Cream', capacity='25g*2'),
]


def match(name, capacity='50g', products=PRODUCTS, **kwargs):
    return match_catalog_product(name, capacity, products, **kwargs)


def test_code_brackets_labels_and_unicode_punctuation_preserve_identity():
    variants = [
        'Test Repair Cream (T-165)', '[T165] Test Repair Cream',
        'T-165 | Test Repair Cream', 'Test Repair Cream【T－165】',
        'Item: Test Repair Cream / SKU: T-165',
        '제품명: Test Repair Cream (제품코드: T165)',
        'Ｔｅｓｔ　Ｒｅｐａｉｒ　Ｃｒｅａｍ（Ｔ－１６５）',
        'test-repair-cream', 'Test\nRepair\tCream', 'Test\u200b Repair Cream',
        '“Test Repair Cream”', 'TestRepairCream',
        'Test (Repair) Cream', 'Test Repair Cream — Capacity: 50 grams',
        'Item No: T165 — Test Repair Cream — Qty: 10 PCS',
        'Test Repair Cream (SKU: T - 165)',
        'Test [T165] Repair Cream', 'Test (SKU: T165) Repair Cream',
    ]
    for name in variants:
        result = match(name)
        assert result['status'] == 'matched'
        assert result['product']['id'] == 'cream50'


def test_full_name_with_extra_description_gets_price_candidate_and_confirmation():
    draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                 seller={'legal_name': 'Acme Supplier Co. Ltd'}, items=[dict(
                     product_name='Test Repair Cream (for dry skin)', capacity='50g',
                     quantity='10', unit_price=None)])
    catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                   supplier_key='ACME_SUPPLIER', currency='KRW', unit_price='1000')])
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0]['unit_price'] == '1000'
    assert any('Confirm product annotation' in c for c in draft['pending_confirmations'])
    apply_verified_catalog_prices(draft, catalog)
    assert len(draft['pending_confirmations']) == 1
    draft['items'][0]['product_name'] = 'Test Repair Cream'
    apply_verified_catalog_prices(draft, catalog)
    assert draft['pending_confirmations'] == []


def test_capacity_units_multipliers_and_decimal_formatting():
    cases = [('Test Repair Cream', '50.0 G', 'cream50'),
             ('Test Hydra Toner', '150 millilitres', 'toner'),
             ('Test Core Ampoule (CX-1)', '5 mL × 6, 7 mL X 6', 'ampoule'),
             ('Test Fiber and Ampoule System', '(1 g + 10 ml) × 6', 'fiber'),
             ('Test Lift Pack Gold (G-1)', '3 g * 10, 100 mL', 'gold'),
             ('Test Core Cream', '2 × 25 grams', 'double')]
    for name, capacity, expected in cases:
        result = match(name, capacity)
        assert result['status'] == 'matched'
        assert result['product']['id'] == expected


def test_codes_and_inline_size_disambiguate_but_do_not_override_conflicts():
    assert match('Test Repair Cream (T165)', None)['product']['id'] == 'cream50'
    assert match('Test Repair Cream [50g]', None)['product']['id'] == 'cream50'
    assert match('Test Repair Cream', None)['status'] == 'ambiguous'
    bad = [('Test Repair Cream (T-166-1)', '50g'),
           ('Test Repair Cream [T999]', '50g'),
           ('Test Repair Cream SKU: T-999', '50g'),
           ('Test Repair Cream Item No: T-999', '50g'),
           ('Test Repair Cream (200g)', '50g'),
           ('Test [T-166-1] Repair Cream', '50g'),
           ('Test Repair Cream (T-165) (T-166-1)', '50g'),
           ('Test Repair Cream / Test Hydra Toner', '50g'),
           ('Not Test Repair Cream', '50g'),
           ('Unrelated Toner (T-165)', '50g')]
    for name, capacity in bad:
        assert match(name, capacity)['status'] != 'matched'


def test_sample_refill_and_formula_variants_are_not_silently_dropped():
    for word in ('Sample', 'Tester', 'Refill', 'Mini', 'Plus', '샘플', '리필', 'new formula'):
        assert match('Test Repair Cream (' + word + ')')['status'] != 'matched'
    products = PRODUCTS + [dict(id='plus', item_name='Test Repair Cream Plus', capacity='50g')]
    assert match('Test Repair Cream Plus', products=products)['product']['id'] == 'plus'


def test_wrong_compound_sizes_and_omitted_product_words_are_rejected():
    for name, size in [('Test Repair Cream', '50ml'),
                       ('Test Core Cream', '50g'),
                       ('Test Core Cream', '25g*3'),
                       ('Test Core Ampoule', '5ml*6'),
                       ('Test Fiber&Ampoule System', '1g+10ml*6'),
                       ('Test Cream', '50g'), ('Test Serum', '100ml'),
                       ('SuperTest Repair Cream', '50g')]:
        assert match(name, size)['status'] != 'matched'


def test_structured_code_must_agree_with_product_name_and_capacity():
    assert match('Test Repair Cream', None, product_code='T165')['product']['id'] == 'cream50'
    assert match('Test Repair Cream', '50g', product_code='T166-1')['status'] != 'matched'
    assert match('Test Hydra Toner', '150ml', product_code='T165')['status'] != 'matched'


def test_high_similarity_ocr_typo_resolves_catalog_candidate_but_requires_double_check():
    result = match('Test Repa1r Cream', '50g')
    assert result['status'] == 'matched'
    assert result['match_method'] == 'fuzzy'
    assert result['product']['id'] == 'cream50'
    assert result['similarity'] >= 0.90
    assert 'Double-check this product' in result['confirmation']
    assert match('Test Repa1r Cream', '50g', product_code='T165')['product']['id'] == 'cream50'
    assert match('Test Repa1r Cream', '50ml')['status'] == 'not_found'
    assert match('Test Repa1r Cream', '50g', product_code='UNKNOWN')['status'] == 'not_found'
    assert match('Test Repa1r Cream', '50g', product_code='T166-1')['status'] == 'not_found'


def test_lower_similarity_returns_review_suggestions_without_auto_match():
    result = match('Test Repaer Crem', '50g')
    assert result['status'] == 'suggested'
    assert result['suggestions'][0]['product']['id'] == 'cream50'
    assert result['suggestions'][0]['similarity'] < 0.90


def test_longer_sku_is_not_mistaken_for_its_prefix():
    products = PRODUCTS + [dict(id='peptide', source_code='T-20-8',
                                item_name='PEPTIDE 5000 SERUM', capacity='100ml')]
    for name in ('PEPTIDE 5000 SERUM SKU: T-20-8', 'T-20-8 | PEPTIDE 5000 SERUM',
                 'PEPTIDE 5000 SERUM (T-20-8)'):
        assert match(name, '100ml', products)['product']['id'] == 'peptide'
    assert match('PEPTIDE 5000 SERUM (T-20)', '100ml', products)['status'] != 'matched'
    for name in ('Test V-C Serum SKU: T-20-999', 'T-20-999 | Test V-C Serum'):
        assert match(name, '100ml', products)['status'] != 'matched'


def test_spf_and_pa_ratings_are_product_identity_not_disposable_punctuation():
    products = [dict(id='sun', item_name='Test Sun Cream SPF50+ PA+++', capacity='70g')]
    assert match('Test Sun Cream SPF 50+ PA+++', '70g', products)['status'] == 'matched'
    for name in ('Test Sun Cream SPF50 PA+', 'Test Sun Cream SPF50+ PA++',
                 'Test Sun Cream SPF50+ PA++++'):
        assert match(name, '70g', products)['status'] != 'matched'


def test_inline_compact_or_annotated_sizes_cannot_override_full_specification():
    for name, size in [('Test Repair Cream 200gx2', '50g'),
                       ('Test Repair Cream (50mg)', '50g'),
                       ('Test Repair Cream (50毫升)', '50g'),
                       ('Test Core Cream 25gx3', '25g*2'),
                       ('Test Core Ampoule (5ml*6 for treatment)', '5ml*6, 7ml*6'),
                       ('Test Fiber&Ampoule System ((1g+10ml)*3 for treatment)', '(1g+10ml)*6')]:
        assert match(name, size)['status'] != 'matched'


def test_duplicate_catalog_and_normalized_name_collisions_remain_ambiguous():
    products = PRODUCTS + [{**PRODUCTS[0], 'id': 'duplicate'}]
    assert match('Test Repair Cream (T165)', products=products)['status'] == 'ambiguous'
    products = PRODUCTS + [dict(id='collision', item_name='Test-Repair Cream', capacity='50g')]
    assert match('TEST REPAIR CREAM', products=products)['status'] == 'ambiguous'


def test_matching_never_mutates_input_and_uses_whole_catalog():
    products = copy.deepcopy(PRODUCTS)
    before = copy.deepcopy(products)
    match('Test Repair Cream (T165)', products=products)
    assert products == before
    # 계약 15.4절: 브랜드 필터를 없앴으므로 product의 brand 키 없이 카탈로그 전체를 찾는다.
    assert match('Test Repair Cream', products=[PRODUCTS[0]])['status'] == 'matched'


def test_match_only_preserves_manual_names_and_document_prices():
    draft = dict(document_type='PL', items=[dict(
        product_name='Test Repaer Crem', capacity='50g', product_id='cream50',
        unit_price='42', price_basis='USD/PCS', price_source='Source document')])
    apply_catalog_product_matches(draft, {'products': PRODUCTS})
    item = draft['items'][0]
    assert item['product_name'] == 'Test Repaer Crem'
    assert item['unit_price'] == '42'
    assert item['price_basis'] == 'USD/PCS'
    assert item['price_source'] == 'Source document'
    assert 'product_id' not in item
    assert any(message.startswith('Double-check this product:')
               for message in draft['pending_confirmations'])

    item['product_name'] = 'Manual product name'
    apply_catalog_product_matches(draft, {'products': PRODUCTS})
    assert item['product_name'] == 'Manual product name'
    assert item['unit_price'] == '42'


def test_catalog_price_is_cleared_if_a_previously_matched_sku_becomes_conflicting():
    draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                 seller={'legal_name': 'Acme Supplier Co. Ltd'}, items=[dict(
                     product_name='Test Repair Cream', capacity='50g', quantity='10')])
    catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                   supplier_key='ACME_SUPPLIER', currency='KRW', unit_price='1000')])
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0]['master_price']
    draft['items'][0]['product_name'] = 'Test Repair Cream (T-166-1)'
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0].get('unit_price') is None
    assert draft['items'][0].get('product_id') is None


def test_high_similarity_imports_price_but_keeps_source_name_and_requires_confirmation():
    draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                 seller={'legal_name': 'Acme Supplier Co. Ltd'}, items=[dict(
                     product_name='Test Repa1r Cream', capacity='50g',
                     quantity='10', unit_price=None)])
    catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                   supplier_key='ACME_SUPPLIER', currency='KRW', unit_price='1000')])
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0]['unit_price'] == '1000'
    assert draft['items'][0]['product_name'] == 'Test Repa1r Cream'
    assert draft['items'][0]['master_price']
    assert any(message.startswith('Double-check this product:')
               for message in draft['pending_confirmations'])


def test_lower_similarity_does_not_import_price_and_preserves_user_entered_name_and_price():
    draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                 seller={'legal_name': 'Acme Supplier Co. Ltd'}, items=[dict(
                     product_name='Test Repaer Crem', capacity='50g',
                     quantity='10', unit_price='42',
                     price_source='User-entered value in document review')])
    catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                   supplier_key='ACME_SUPPLIER', currency='KRW', unit_price='1000')])
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0].get('product_id') is None
    assert not draft['items'][0]['master_price']
    assert draft['items'][0]['unit_price'] == '42'
    assert any(message.startswith('Double-check this product:')
               for message in draft['pending_confirmations'])
    draft['items'][0]['product_name'] = 'Customer-entered product name'
    apply_verified_catalog_prices(draft, catalog)
    assert draft['items'][0]['product_name'] == 'Customer-entered product name'
    assert draft['items'][0]['unit_price'] == '42'
