"""PO/PI promotion command, quantity completion, and paid/free amount regression."""
import copy
import unittest
import tempfile
from pathlib import Path
from zipfile import ZipFile
import struct
import zlib

from Quotation_KEKOREA.agent.promotions import apply_promotion_commands, recalculate_order_promotions, normalize_promotion
from Quotation_KEKOREA.agent.trade_documents import validate_and_calculate
from Quotation_KEKOREA.agent.review_fields import apply_review_value, missing_review_fields
from Quotation_KEKOREA.tests.test_review_fields import complete_draft


RULES = {'1+1': ('10', '20'), '2+1': ('5', '15'), '3+1': ('3', '13'),
         '4+1': ('2', '12'), '4+3': ('6', '16'), '3+2': ('6', '16')}


def order(dtype='PI'):
    draft = complete_draft()
    draft.update(document_type=dtype, product_family='other')
    draft['buyer']['legal_name'] = 'KE KOREA' if dtype == 'PO' else 'Test Buyer'
    draft['seller']['legal_name'] = 'Test Supplier' if dtype == 'PO' else 'KE KOREA'
    draft['items'][0].update(product_name='Test Toner', quantity='10', paid_quantity='10',
                             free_quantity='0', shipped_quantity='10', unit_price='2',
                             price_basis='PCS', price_source='User supplied')
    return draft


class OrderPromotionTests(unittest.TestCase):
    def test_six_global_commands_compute_free_shipping_and_charge_only_paid_units(self):
        for dtype in ('PI', 'PO'):
            for rule, (free, shipped) in RULES.items():
                with self.subTest(dtype=dtype, rule=rule):
                    draft = order(dtype)
                    apply_promotion_commands(draft, f'All products {rule} promotion')
                    result = validate_and_calculate(draft)
                    self.assertEqual(result['items'][0]['promotion'], rule)
                    self.assertEqual(result['items'][0]['free_quantity'], free)
                    self.assertEqual(result['items'][0]['shipped_quantity'], shipped)
                    self.assertEqual(result['items'][0]['line_total'], '20.00')

    def test_english_korean_and_fullwidth_rule_text_normalizes(self):
        for text in ('3+1', '3 + 1 event', 'Buy 3, get 1 free', 'buy 3 get 1 free',
                     '3개 구매 시 1개 증정', '３＋１ 행사'):
            with self.subTest(text=text):
                self.assertEqual(normalize_promotion(text), '3+1')
        for text in ('2+1 or 3+1', '0+1', '-1+1', 'unknown'):
            with self.subTest(text=text):
                self.assertIsNone(normalize_promotion(text))

    def test_named_rules_and_global_default_do_not_touch_other_products(self):
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Serum'})
        apply_promotion_commands(draft, 'Test Toner 4+3; Test Cream 3+2')
        self.assertEqual([r.get('promotion') for r in draft['items']], ['4+3', '3+2', None])
        self.assertEqual([r['free_quantity'] for r in draft['items']], ['6', '6', '0'])
        self.assertEqual(len(draft['items']), 3)

    def test_named_capacity_limits_event_to_that_ordered_variant(self):
        draft = order()
        draft['items'][0]['capacity'] = '50g'
        draft['items'].append({**draft['items'][0], 'capacity': '200g'})
        apply_promotion_commands(draft, 'Test Toner 50 g 3+1')
        self.assertEqual(draft['items'][0].get('promotion'), '3+1')
        self.assertIsNone(draft['items'][1].get('promotion'))

    def test_single_unscoped_command_applies_to_uploaded_order_rows(self):
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
        apply_promotion_commands(draft, 'Dear Glow에 PI 작성. 3+1 행사 적용')
        self.assertEqual([r['promotion'] for r in draft['items']], ['3+1', '3+1'])

    def test_event_scope_survives_exceptions_quantities_and_model_overreach(self):
        for prompt, expected, error in [
                ('All products 3+1 except Test Cream', [None, None], True),
                ('All Test Toner 3+1', ['3+1', None], False),
                ('Test Toner 10 pcs 3+1', ['3+1', None], False),
                ('Create PI. Test Toner 10 units, Test Cream 10 units. 3+1 promotion', ['3+1', '3+1'], False)]:
            with self.subTest(prompt=prompt):
                draft = order()
                draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
                apply_promotion_commands(draft, prompt)
                self.assertEqual([r.get('promotion') for r in draft['items']], expected)
                self.assertEqual(bool(draft.get('conflicts')), error)
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream',
                               'promotion': '3+1', 'free_quantity': '3', 'shipped_quantity': '13'})
        apply_promotion_commands(draft, 'Test Toner 3+1')
        self.assertIsNone(draft['items'][1].get('promotion'))
        self.assertEqual(draft['items'][1]['free_quantity'], '0')
        self.assertEqual(draft['items'][1]['shipped_quantity'], '10')

    def test_named_override_preserves_image_supported_events_and_manual_foc(self):
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream',
                               'promotion': '3+1', 'source': 'Test Cream 10 PCS 3+1'})
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Serum',
                               'free_quantity': '2', 'shipped_quantity': '12'})
        apply_promotion_commands(draft, 'Test Toner 2+1')
        self.assertEqual(draft['items'][1]['promotion'], '3+1')
        self.assertEqual(draft['items'][1]['free_quantity'], '3')
        self.assertEqual(draft['items'][2]['free_quantity'], '2')
        draft = order()
        draft['items'].append({**draft['items'][0], 'product_name': 'Test Cream'})
        apply_promotion_commands(draft, 'All products 3+1; Test Cream 4+3')
        self.assertEqual([r['promotion'] for r in draft['items']], ['3+1', '4+3'])

    def test_existing_model_english_promotion_recalculates_without_prompt_rule(self):
        draft = order()
        draft['items'][0]['promotion'] = 'Buy 3, get 1 free'
        apply_promotion_commands(draft, 'Create a PI')
        self.assertEqual(draft['items'][0]['promotion'], '3+1')
        self.assertEqual(draft['items'][0]['free_quantity'], '3')

    def test_late_quantity_completion_recalculates_all_six_rules(self):
        for dtype in ('PO', 'PI'):
            for rule, (free, shipped) in RULES.items():
                with self.subTest(dtype=dtype, rule=rule):
                    draft = order(dtype)
                    draft['items'][0].update(promotion=rule, quantity=None, paid_quantity=None, shipped_quantity=None)
                    field = next(f for f in missing_review_fields(draft) if f.path == ('items', 0, 'quantity'))
                    apply_review_value(draft, field, '10')
                    result = validate_and_calculate(draft)
                    self.assertEqual(result['items'][0]['free_quantity'], free)
                    self.assertEqual(result['items'][0]['shipped_quantity'], shipped)
                    self.assertFalse(any('Promotion quantity mismatch' in s for s in result['blocking_issues']))

    def test_zero_remainders_and_fractional_paid_units(self):
        for paid, expected in (('0', '0'), ('2', '0'), ('3', '1'), ('4', '1'), ('7', '2')):
            draft = order()
            draft['items'][0].update(promotion='3+1', quantity=paid, paid_quantity=paid)
            result = recalculate_order_promotions(draft)
            self.assertEqual(result['items'][0]['free_quantity'], expected)
        for paid in ('-1', 'NaN', '2.5'):
            draft = order()
            draft['items'][0].update(promotion='3+1', quantity=paid, paid_quantity=paid)
            result = validate_and_calculate(draft)
            self.assertTrue(result['blocking_issues'])

    def test_no_rule_and_non_order_documents_are_unchanged(self):
        draft = order()
        before = copy.deepcopy(draft)
        self.assertEqual(recalculate_order_promotions(draft), before)
        apply_promotion_commands(draft, 'Create a PI at list price')
        self.assertEqual(draft, before)
        for dtype in ('CI', 'PL'):
            draft = order(dtype)
            draft['items'][0]['promotion'] = 'Buy 3, get 1 free'
            before = copy.deepcopy(draft)
            apply_promotion_commands(draft, 'All products 3+1')
            self.assertEqual(draft, before)
            self.assertEqual(recalculate_order_promotions(draft), before)

    def test_conflicting_or_negated_commands_are_not_silently_chosen(self):
        for prompt in ('All products 2+1 or 3+1', 'All products 3+1 적용하지마'):
            with self.subTest(prompt=prompt):
                draft = order()
                apply_promotion_commands(draft, prompt)
                self.assertTrue(any('Promotion command' in c for c in draft.get('conflicts', [])))

    def test_validator_does_not_mutate_original_promotion_quantities(self):
        draft = order()
        draft['items'][0]['promotion'] = '3+1'
        before = copy.deepcopy(draft)
        validate_and_calculate(draft)
        self.assertEqual(draft, before)

    def test_po_pi_files_show_foc_and_charge_only_paid_for_all_six_events(self):
        from Quotation_KEKOREA.agent.renderers import render_files
        bank = {key: 'TEST' for key in ('beneficiary', 'bank_name', 'branch', 'swift', 'account_number', 'bank_address')}
        with tempfile.TemporaryDirectory() as directory:
            def chunk(kind, body):
                return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body) & 0xffffffff)
            seal = Path(directory) / 'synthetic-seal.png'
            seal.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
                             + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))
            for dtype in ('PO', 'PI'):
                for rule, (free, shipped) in RULES.items():
                    with self.subTest(dtype=dtype, rule=rule):
                        draft = order(dtype)
                        draft['items'][0]['promotion'] = rule
                        result = validate_and_calculate(draft)
                        files = render_files(result, directory, bank_details=bank, seal_path=seal)
                        pdf = files['pdf'].read_bytes()
                        self.assertTrue(pdf.startswith(b'%PDF'))
                        self.assertTrue(f'10 + {free} FOC'.encode() in pdf, 'PDF must show paid units plus correct FOC units')
                        self.assertEqual(result['total'], '20.00')
                        with ZipFile(files['xlsx']) as book:
                            sheet = book.read('xl/worksheets/sheet1.xml').decode()
                        self.assertIn('FREE OF CHARGE', sheet)
