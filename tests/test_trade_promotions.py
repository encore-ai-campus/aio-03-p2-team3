"""PO/PI 행사 명령 pytest(원본 tests/test_order_promotions.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_order_promotions.py
- 렌더러 출력 시험(test_po_pi_files_show_foc_and_charge_only_paid_for_all_six_events)은
  kekorea-port 4절(C 문서 출력) 범위라 여기에 두지 않았다.
- 발행사·거래처 이름은 가상 값으로 바꿨다.
"""
import copy

from app.trade.common.promotions import (
    apply_promotion_commands,
    normalize_promotion,
    recalculate_order_promotions,
)
from app.trade.common.review_fields import apply_review_value, missing_review_fields
from app.trade.common.trade_documents import validate_and_calculate


RULES = {'1+1': ('10', '20'), '2+1': ('5', '15'), '3+1': ('3', '13'),
         '4+1': ('2', '12'), '4+3': ('6', '16'), '3+2': ('6', '16')}

ISSUER_NAME = 'Testworks Trading Co'
ISSUER_KEY = 'testworkstrading'


def complete_draft():
    party = {"legal_name": "Company", "address": "Address", "contact": "N/A", "phone": "N/A", "email": "N/A"}
    return {"document_type": "PI", "currency": "USD", "document_number": "DRAFT",
            "buyer": dict(party), "seller": dict(party), "incoterms": "EXW Seoul",
            "payment_terms": "Advance payment", "ship_to": "N/A", "country_of_origin": "Korea",
            "shipment_reference": "N/A", "items": [{"product_name": "Cell", "quantity": "10",
                "paid_quantity": "10", "unit": "PCS", "unit_price": "1", "discount_percent": "0"}]}


def order(dtype='PI'):
    draft = complete_draft()
    draft.update(document_type=dtype, product_family='other')
    draft['buyer']['legal_name'] = ISSUER_NAME if dtype == 'PO' else 'Test Buyer'
    draft['seller']['legal_name'] = 'Test Supplier' if dtype == 'PO' else ISSUER_NAME
    draft['items'][0].update(product_name='Test Toner', quantity='10', paid_quantity='10',
                             free_quantity='0', shipped_quantity='10', unit_price='2',
                             price_basis='PCS', price_source='User supplied')
    return draft


def calculate(draft):
    return validate_and_calculate(draft, issuer_key=ISSUER_KEY)


def test_six_global_commands_compute_free_shipping_and_charge_only_paid_units():
    for dtype in ('PI', 'PO'):
        for rule, (free, shipped) in RULES.items():
            draft = order(dtype)
            apply_promotion_commands(draft, f'All products {rule} promotion')
            result = calculate(draft)
            assert result['items'][0]['promotion'] == rule
            assert result['items'][0]['free_quantity'] == free
            assert result['items'][0]['shipped_quantity'] == shipped
            assert result['items'][0]['line_total'] == '20.00'


def test_english_korean_and_fullwidth_rule_text_normalizes():
    for text in ('3+1', '3 + 1 event', 'Buy 3, get 1 free', 'buy 3 get 1 free',
                 '3개 구매 시 1개 증정', '３＋１ 행사'):
        assert normalize_promotion(text) == '3+1'
    for text in ('2+1 or 3+1', '0+1', '-1+1', 'unknown'):
        assert normalize_promotion(text) is None


def test_named_rules_and_global_default_do_not_touch_other_products():
    draft = order()
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Serum'})
    apply_promotion_commands(draft, 'Test Toner 4+3; Test Cream 3+2')
    assert [r.get('promotion') for r in draft['items']] == ['4+3', '3+2', None]
    assert [r['free_quantity'] for r in draft['items']] == ['6', '6', '0']
    assert len(draft['items']) == 3


def test_named_capacity_limits_event_to_that_ordered_variant():
    draft = order()
    draft['items'][0]['capacity'] = '50g'
    draft['items'].append({**draft['items'][0], 'capacity': '200g'})
    apply_promotion_commands(draft, 'Test Toner 50 g 3+1')
    assert draft['items'][0].get('promotion') == '3+1'
    assert draft['items'][1].get('promotion') is None


def test_single_unscoped_command_applies_to_uploaded_order_rows():
    draft = order()
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
    apply_promotion_commands(draft, 'Acme Buyer에 PI 작성. 3+1 행사 적용')
    assert [r['promotion'] for r in draft['items']] == ['3+1', '3+1']


def test_event_scope_survives_exceptions_quantities_and_model_overreach():
    for prompt, expected, error in [
            ('All products 3+1 except Test Cream', [None, None], True),
            ('All Test Toner 3+1', ['3+1', None], False),
            ('Test Toner 10 pcs 3+1', ['3+1', None], False),
            ('Create PI. Test Toner 10 units, Test Cream 10 units. 3+1 promotion', ['3+1', '3+1'], False)]:
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
        apply_promotion_commands(draft, prompt)
        assert [r.get('promotion') for r in draft['items']] == expected
        assert bool(draft.get('conflicts')) == error
    draft = order()
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream',
                           'promotion': '3+1', 'free_quantity': '3', 'shipped_quantity': '13'})
    apply_promotion_commands(draft, 'Test Toner 3+1')
    assert draft['items'][1].get('promotion') is None
    assert draft['items'][1]['free_quantity'] == '0'
    assert draft['items'][1]['shipped_quantity'] == '10'


def test_named_override_preserves_image_supported_events_and_manual_foc():
    draft = order()
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream',
                           'promotion': '3+1', 'source': 'Test Cream 10 PCS 3+1'})
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Serum',
                           'free_quantity': '2', 'shipped_quantity': '12'})
    apply_promotion_commands(draft, 'Test Toner 2+1')
    assert draft['items'][1]['promotion'] == '3+1'
    assert draft['items'][1]['free_quantity'] == '3'
    assert draft['items'][2]['free_quantity'] == '2'
    draft = order()
    draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
    apply_promotion_commands(draft, 'All products 3+1; Test Cream 4+3')
    assert [r['promotion'] for r in draft['items']] == ['3+1', '4+3']


def test_existing_model_english_promotion_recalculates_without_prompt_rule():
    draft = order()
    draft['items'][0]['promotion'] = 'Buy 3, get 1 free'
    apply_promotion_commands(draft, 'Create a PI')
    assert draft['items'][0]['promotion'] == '3+1'
    assert draft['items'][0]['free_quantity'] == '3'


def test_late_quantity_completion_recalculates_all_six_rules():
    for dtype in ('PO', 'PI'):
        for rule, (free, shipped) in RULES.items():
            draft = order(dtype)
            draft['items'][0].update(promotion=rule, quantity=None, paid_quantity=None, shipped_quantity=None)
            field = next(f for f in missing_review_fields(draft) if f.path == ('items', 0, 'quantity'))
            apply_review_value(draft, field, '10')
            result = calculate(draft)
            assert result['items'][0]['free_quantity'] == free
            assert result['items'][0]['shipped_quantity'] == shipped
            assert not any('Promotion quantity mismatch' in s for s in result['blocking_issues'])


def test_zero_remainders_and_fractional_paid_units():
    for paid, expected in (('0', '0'), ('2', '0'), ('3', '1'), ('4', '1'), ('7', '2')):
        draft = order()
        draft['items'][0].update(promotion='3+1', quantity=paid, paid_quantity=paid)
        result = recalculate_order_promotions(draft)
        assert result['items'][0]['free_quantity'] == expected
    for paid in ('-1', 'NaN', '2.5'):
        draft = order()
        draft['items'][0].update(promotion='3+1', quantity=paid, paid_quantity=paid)
        result = calculate(draft)
        assert result['blocking_issues']


def test_no_rule_and_non_order_documents_are_unchanged():
    draft = order()
    before = copy.deepcopy(draft)
    assert recalculate_order_promotions(draft) == before
    apply_promotion_commands(draft, 'Create a PI at list price')
    assert draft == before
    for dtype in ('CI', 'PL'):
        draft = order(dtype)
        draft['items'][0]['promotion'] = 'Buy 3, get 1 free'
        before = copy.deepcopy(draft)
        apply_promotion_commands(draft, 'All products 3+1')
        assert draft == before
        assert recalculate_order_promotions(draft) == before


def test_conflicting_or_negated_commands_are_not_silently_chosen():
    for prompt in ('All products 2+1 or 3+1', 'All products 3+1 적용하지마'):
        draft = order()
        apply_promotion_commands(draft, prompt)
        assert any('Promotion command' in c for c in draft.get('conflicts', []))


def test_validator_does_not_mutate_original_promotion_quantities():
    draft = order()
    draft['items'][0]['promotion'] = '3+1'
    before = copy.deepcopy(draft)
    calculate(draft)
    assert draft == before
