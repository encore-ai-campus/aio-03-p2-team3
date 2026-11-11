"""Manual PI samples must stay outside the catalog and inside invoice totals."""
import copy
import unittest
import tempfile
from pathlib import Path
from zipfile import ZipFile
import struct
import zlib

from Quotation_KEKOREA.agent.samples import ensure_sample_rows, new_sample, update_sample
from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices
from Quotation_KEKOREA.agent.trade_documents import validate_and_calculate
from Quotation_KEKOREA.agent.renderers import _rows
from Quotation_KEKOREA.tests.test_order_promotions import order


class PiSampleTests(unittest.TestCase):
    def test_keyword_opens_one_manual_row_without_duplicate_or_other_document_changes(self):
        for word in ('샘플', 'SAMPLE', 'sample', 'SaMpLe', 'SAMPLE도 있어', 'sample도'):
            doc = order()
            ensure_sample_rows(doc, f'Dearglow PI {word}')
            ensure_sample_rows(doc, f'Dearglow PI {word}')
            self.assertEqual(len(doc['items']), 2)
            self.assertTrue(doc['items'][-1]['is_sample'])
            self.assertIsNone(doc['items'][-1]['product_name'])
            self.assertIsNone(doc['items'][-1]['quantity'])
            self.assertIsNone(doc['items'][-1]['unit_price'])
        for dtype, prompt in (('PO', 'sample'), ('CI', '샘플'), ('PI', 'regular order')):
            doc = order(dtype)
            before = copy.deepcopy(doc)
            ensure_sample_rows(doc, prompt)
            self.assertEqual(doc, before)

    def test_regular_discount_confirmation_ignores_independent_manual_samples(self):
        from Quotation_KEKOREA.agent.review_fields import apply_review_value, missing_review_fields
        doc = order()
        doc['items'][0]['discount_percent'] = None
        doc['conflicts'] = ['Discount was mentioned without a percentage; specify a single discount rate.']
        doc['items'].append(new_sample())
        field = next(f for f in missing_review_fields(doc) if f.path == ('items', 0, 'discount_percent'))
        apply_review_value(doc, field, '10')
        self.assertFalse(doc['conflicts'])
        self.assertEqual(doc['items'][1]['discount_percent'], '0')

    def test_existing_sample_is_editable_without_creating_an_extra_row(self):
        doc = order()
        doc['items'].append(dict(product_name='Toner SAMPLE', quantity='5', unit_price='0'))
        ensure_sample_rows(doc, '샘플도 있어')
        self.assertEqual(len(doc['items']), 2)
        self.assertTrue(doc['items'][-1]['is_sample'])

    def test_zero_and_positive_sample_prices_are_included_in_quantity_and_amount(self):
        for price, amount in (('0', '20.00'), ('0.25', '21.25')):
            doc = order()
            doc['product_family'] = 'cosmetics'
            doc['items'][0]['price_override_confirmed'] = True
            item = new_sample()
            update_sample(item, name='Trial Toner', capacity='2ml', quantity='5', unit='PCS', price=price)
            doc['items'].append(item)
            result = validate_and_calculate(doc)
            self.assertFalse(result['blocking_issues'], result['blocking_issues'])
            self.assertEqual(result['total'], amount)
            self.assertEqual(sum(int(i['display_quantity']) for i in result['items']), 15)
            rows = _rows(result)
            self.assertEqual(rows[-1][1], 'Trial Toner')
            self.assertEqual(rows[-1][3], '5')
            self.assertEqual(rows[-1][5], '$' + ('0.00' if price == '0' else '0.25'))

    def test_catalog_never_overwrites_sample_even_when_name_matches_product(self):
        doc = order()
        doc.update(product_family='cosmetics', buyer={'legal_name': 'Dear Glow'})
        item = new_sample()
        update_sample(item, name='Trial Toner', capacity='2ml', quantity='5', unit='PCS', price='0')
        doc['items'] = [item]
        seed = {'products': [{'id': 'p1', 'item_name': item['product_name'], 'capacity': '2ml'}],
                'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW', 'currency': 'USD', 'unit_price': '25'}]}
        before = copy.deepcopy(seed)
        apply_verified_eclado_prices(doc, seed)
        self.assertEqual(item['unit_price'], '0')
        self.assertFalse(item['master_price'])
        self.assertFalse(any('SAMPLE' in s for s in doc['missing_fields']))
        self.assertEqual(seed, before)

    def test_invalid_or_missing_manual_values_block_sample(self):
        for quantity, price in ((None, None), ('-1', '0'), ('NaN', '0'), ('5', '-1'), ('5', 'Infinity')):
            doc = order()
            item = new_sample()
            update_sample(item, name='Trial Toner', capacity='', quantity=quantity, unit='PCS', price=price)
            doc['items'].append(item)
            result = validate_and_calculate(doc)
            self.assertTrue(any(s.startswith('Sample ') for s in result['blocking_issues']))

    def test_regular_item_and_other_documents_still_require_positive_prices(self):
        for dtype in ('PI', 'PO', 'CI'):
            doc = order(dtype)
            doc['items'][0].update(unit_price='0', is_sample=dtype != 'PI')
            result = validate_and_calculate(doc)
            self.assertTrue(any('positive number required for unit price' in s for s in result['blocking_issues']))

    def test_sample_does_not_receive_all_product_promotion(self):
        from Quotation_KEKOREA.agent.promotions import apply_promotion_commands
        doc = order()
        doc['items'].append(new_sample())
        update_sample(doc['items'][-1], name='Trial Toner', capacity='', quantity='5', unit='PCS', price='0')
        apply_promotion_commands(doc, 'All products 3+1')
        self.assertEqual(doc['items'][0]['free_quantity'], '3')
        self.assertEqual(doc['items'][1]['free_quantity'], '0')
        self.assertFalse(doc['items'][1].get('promotion'))

    def test_actual_invoice_files_include_sample_line_quantity_and_total(self):
        from Quotation_KEKOREA.agent.renderers import render_files
        from Quotation_KEKOREA.agent.pi_pdf import _total_quantity_summary
        bank = {key: 'TEST' for key in ('beneficiary', 'bank_name', 'branch', 'swift', 'account_number', 'bank_address')}
        with tempfile.TemporaryDirectory() as directory:
            def chunk(kind, body):
                return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body) & 0xffffffff)
            seal = Path(directory) / 'synthetic-seal.png'
            seal.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
                             + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))
            for price, expected in (('0', '20.00'), ('0.25', '21.25')):
                doc = order()
                item = new_sample()
                update_sample(item, name='Trial Toner', capacity='2ml', quantity='5', unit='PCS', price=price)
                doc['items'].append(item)
                result = validate_and_calculate(doc)
                self.assertEqual(_total_quantity_summary(result['items']), '15 PCS')
                files = render_files(result, directory, bank_details=bank, seal_path=seal)
                pdf = files['pdf'].read_bytes()
                self.assertTrue(b'Trial Toner' in pdf, 'PDF must include the user-entered product name')
                self.assertTrue(b'15 PCS' in pdf, 'PDF must sum sample and ordinary quantities')
                self.assertTrue(expected.encode() in pdf, 'PDF must include manually priced sample in amount')
                with ZipFile(files['xlsx']) as book:
                    sheet = book.read('xl/worksheets/sheet1.xml').decode()
                self.assertIn('Trial Toner', sheet)
                self.assertNotIn('Trial Toner (SAMPLE)', sheet)
                self.assertIn(expected, sheet)

    def test_manual_product_name_remains_exactly_as_entered_and_can_be_edited(self):
        item = new_sample()
        for name in ('Trial Toner', 'Cell Memory Cream', 'Trial Toner (2ml)', 'SAMPLE Kit A'):
            update_sample(item, name=name, capacity='2ml', quantity='5', unit='PCS', price='0')
            self.assertEqual(item['product_name'], name)
            self.assertTrue(item['is_sample'])

    def test_sample_does_not_weaken_regular_cosmetics_category_or_price_guards(self):
        seed = {'products': [{'id': 'p1', 'item_name': 'Test Toner', 'capacity': '50ml', 'brand': 'ECLADO'}]}
        for with_sample in (False, True):
            doc = order()
            doc['items'][0].update(capacity='50ml', unit_price=None)
            if with_sample:
                doc['items'].append(new_sample())
            apply_verified_eclado_prices(doc, seed)
            self.assertEqual(doc['product_family'], 'cosmetics')
            self.assertTrue(any('transaction-specific price for Test Toner' in s for s in doc['missing_fields']))
