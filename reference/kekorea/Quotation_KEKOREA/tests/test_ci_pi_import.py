"""PI attachment import preserves commercial facts without changing CI renderers."""
import copy
import unittest
import tempfile
from pathlib import Path
from zipfile import ZipFile
import struct
import zlib
from Quotation_KEKOREA.agent.ci_import import (prepare_ci_import, apply_document_prices,
    ci_import_issues, ci_render_data)
from Quotation_KEKOREA.agent.trade_documents import validate_and_calculate
from Quotation_KEKOREA.tests.test_order_promotions import order


def pi_source():
    doc = order()
    doc.update(source_document_type='PI', source_total='18.00', payment_terms='TT TEST PAYMENT',
               bank_details={'account': 'TEST ACCOUNT'}, remarks='BANK INFORMATION: TEST BANK',
               product_family='cosmetics')
    doc['items'][0].update(discount_percent='10', source='Test Toner 10 PCS USD 2.00 10% 18.00',
                           source_line_total='18.00')
    return doc


class CiPiImportTests(unittest.TestCase):
    def test_import_keeps_rows_parties_currency_and_terms_but_excludes_payment_data(self):
        doc = pi_source()
        rows, buyer = copy.deepcopy(doc['items']), copy.deepcopy(doc['buyer'])
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertTrue(doc['_ci_from_pi'])
        self.assertEqual(doc['document_type'], 'CI')
        self.assertEqual(doc['buyer'], buyer)
        for key in ('product_name', 'quantity', 'unit_price', 'discount_percent'):
            self.assertEqual(doc['items'][0][key], rows[0][key])
        self.assertEqual(doc['payment_terms'], 'N/A')
        self.assertNotIn('bank_details', doc)
        self.assertEqual(doc['remarks'], 'N/A')

    def test_catalog_refresh_never_changes_prices_on_imported_pi(self):
        doc = pi_source()
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        seed = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Toner'}],
                'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW', 'currency': 'USD', 'unit_price': '99'}]}
        apply_document_prices(doc, seed)
        self.assertEqual(doc['items'][0]['unit_price'], '2')
        self.assertEqual(doc['items'][0]['discount_percent'], '10')
        result = validate_and_calculate(doc)
        self.assertEqual(result['total'], '18.00')
        self.assertEqual(ci_import_issues(result), [])

    def test_import_defaults_omitted_discount_to_zero_when_source_has_no_discount_evidence(self):
        doc = pi_source()
        doc.update(source_total='20.00')
        doc['items'][0].update(discount_percent=None, source_line_total='20.00',
                               source='Test Toner 10 PCS USD 2.00 20.00')
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertEqual(doc['items'][0]['discount_percent'], '0')
        result = validate_and_calculate(doc)
        self.assertFalse(any('discount' in issue.lower() for issue in result['blocking_issues']))
        self.assertEqual(ci_import_issues(result), [])

    def test_import_clears_only_missing_notices_for_fields_filled_during_review(self):
        doc = pi_source()
        doc.update(document_number='CI-TEST', shipment_reference='SHIP-TEST',
                   country_of_origin='South Korea')
        doc['buyer'].update(legal_name='Test Buyer', address='Test Buyer Address')
        doc['missing_fields'] = [
            'Buyer legal name and address: the source identifies the consignee, not explicitly as buyer.',
            'Commercial invoice number',
            'Shipment reference',
            'Country of origin',
            'HS codes',
        ]
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertEqual(doc['missing_fields'], ['HS codes'])

    def test_import_keeps_missing_party_and_document_notices_until_fields_are_filled(self):
        doc = pi_source()
        doc['document_number'] = None
        doc['buyer'].update(legal_name=None, address=None)
        doc['missing_fields'] = ['Buyer legal name and address: buyer not explicit.',
                                 'Commercial invoice number']
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertEqual(doc['missing_fields'], ['Buyer legal name and address: buyer not explicit.',
                                                 'Commercial invoice number'])

    def test_import_keeps_discount_review_when_source_mentions_discount_but_rate_is_missing(self):
        doc = pi_source()
        doc['items'][0].update(discount_percent=None,
                               source='Test Toner 10 PCS USD 2.00 discount 18.00')
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertIsNone(doc['items'][0]['discount_percent'])
        result = validate_and_calculate(doc)
        self.assertTrue(any('Confirm discount percentage' in issue
                            for issue in result['blocking_issues']))
        self.assertTrue(any('discount' in issue.lower() for issue in ci_import_issues(result)))

    def test_ci_import_matches_product_without_replacing_pi_transaction_price(self):
        doc = pi_source()
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        item = doc['items'][0]
        seed = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': item['product_name'],
                              'capacity': item.get('capacity')}],
                'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW',
                                  'currency': 'USD', 'unit_price': '99'}]}
        original_price, original_basis, original_source = (
            item['unit_price'], item['price_basis'], item['price_source'])
        apply_document_prices(doc, seed)
        self.assertEqual(item['product_id'], 'p1')
        self.assertEqual(item['unit_price'], original_price)
        self.assertEqual(item['price_basis'], original_basis)
        self.assertEqual(item['price_source'], original_source)

    def test_ci_without_pi_does_not_use_catalog_price_and_is_blocked(self):
        doc = order('CI')
        doc['items'][0]['unit_price'] = None
        seed = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Toner'}],
                'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW',
                                  'currency': 'USD', 'unit_price': '99'}]}
        apply_document_prices(doc, seed)
        self.assertIsNone(doc['items'][0]['unit_price'])
        self.assertIn('CI must be created from an attached PI to use its transaction prices',
                      ci_import_issues(doc))

    def test_pl_matches_product_without_applying_catalog_price(self):
        doc = order('PL')
        doc['items'][0]['product_name'] = 'Test Toner'
        doc['items'][0]['capacity'] = '150ml'
        doc['items'][0]['unit_price'] = '42'
        seed = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Toner',
                              'capacity': '150ml'}],
                'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ECLADO',
                                     'currency': 'KRW', 'unit_price': '8000'}]}
        apply_document_prices(doc, seed)
        self.assertEqual(doc['items'][0]['product_id'], 'p1')
        self.assertEqual(doc['items'][0]['unit_price'], '42')

    def test_source_line_and_total_mismatches_are_actionable(self):
        doc = pi_source()
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        doc['source_total'] = '19.00'
        doc['items'][0]['source_line_total'] = '19.00'
        issues = ci_import_issues(validate_and_calculate(doc))
        self.assertTrue(any('total' in i.lower() for i in issues))
        self.assertTrue(any('item 1' in i.lower() for i in issues))

    def test_imported_zero_price_sample_is_preserved_with_ordinary_positive_price_guard_intact(self):
        doc = pi_source()
        doc['items'].append(dict(product_name='Trial Toner', quantity='5', paid_quantity='5', unit='PCS',
                                 unit_price='0', discount_percent='0', source_line_total='0',
                                 source='Trial Toner 5 PCS USD 0.00'))
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        result = validate_and_calculate(doc)
        self.assertFalse(result['blocking_issues'], result['blocking_issues'])
        self.assertEqual(result['items'][1]['line_total'], '0.00')
        regular = order('CI')
        regular['items'][0]['unit_price'] = '0'
        self.assertTrue(any('positive number required for unit price' in s
                            for s in validate_and_calculate(regular)['blocking_issues']))

    def test_pi_and_po_workflows_remain_unchanged_and_ci_requires_pi(self):
        for dtype, attached, source in (('PI', True, 'PI'), ('PO', True, 'PI'), ('CI', False, 'PI'), ('CI', True, 'PO')):
            doc = order(dtype)
            doc['source_document_type'] = source
            before = copy.deepcopy(doc)
            prepare_ci_import(doc, requested_type=dtype, has_attachments=attached)
            self.assertEqual(doc, before)
            if dtype == 'CI':
                self.assertIn('CI must be created from an attached PI to use its transaction prices',
                              ci_import_issues(doc))
            else:
                self.assertEqual(ci_import_issues(doc), [])
            self.assertEqual(ci_render_data(doc), doc)

    def test_render_adapter_keeps_existing_ci_paid_plus_foc_display_correct_without_mutation(self):
        doc = pi_source()
        doc['items'][0].update(free_quantity='3', shipped_quantity='13', display_quantity='13')
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        before = copy.deepcopy(doc)
        output = ci_render_data(doc)
        self.assertEqual(output['items'][0]['display_quantity'], '10')
        self.assertEqual(output['items'][0]['shipped_quantity'], '13')
        self.assertEqual(doc, before)

    def test_actual_ci_files_preserve_foc_sample_and_totals_without_pi_bank_or_payment_values(self):
        from Quotation_KEKOREA.agent.renderers import render_files
        doc = pi_source()
        doc['shipment_reference'] = 'TEST-SHIPMENT'
        doc['items'][0].update(free_quantity='3', shipped_quantity='13')
        doc['items'].append(dict(product_name='Trial Toner', quantity='5', paid_quantity='5', unit='PCS',
                                 unit_price='0', discount_percent='0', source_line_total='0',
                                 source='Trial Toner 5 PCS USD 0.00'))
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        result = validate_and_calculate(doc)
        self.assertEqual(ci_import_issues(result), [])
        with tempfile.TemporaryDirectory() as directory:
            def chunk(kind, body):
                return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body) & 0xffffffff)
            seal = Path(directory) / 'synthetic-seal.png'
            seal.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
                             + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))
            bank = {key: 'DO_NOT_COPY_BANK_VALUE' for key in ('BENEFICIARY', 'BANK_NAME', 'BRANCH', 'SWIFT', 'ACCOUNT_NUMBER', 'BANK_ADDRESS')}
            files = render_files(ci_render_data(result), directory, bank_details=bank, seal_path=seal)
            pdf = files['pdf'].read_bytes()
            self.assertTrue(b'COMMERCIAL INVOICE' in pdf)
            self.assertTrue(b'10 + 3 FOC' in pdf, 'CI must show original paid plus FOC quantity')
            self.assertTrue(b'18 PCS' in pdf, 'CI shipping total must include FOC and samples once')
            self.assertTrue(b'Trial Toner' in pdf and b'18.00' in pdf)
            with ZipFile(files['xlsx']) as book:
                sheet = book.read('xl/worksheets/sheet1.xml')
            for raw in (pdf, sheet, files['html'].read_bytes()):
                self.assertTrue(b'DO_NOT_COPY_BANK_VALUE' not in raw, 'CI must exclude bank values')
                self.assertTrue(b'TT TEST PAYMENT' not in raw, 'CI must exclude PI payment values')

    def test_explicit_conversion_command_is_distinct_from_creating_a_pi(self):
        from Quotation_KEKOREA.agent.ci_import import is_ci_conversion_request
        self.assertTrue(is_ci_conversion_request('Convert PI to CI'))
        self.assertTrue(is_ci_conversion_request('첨부 PI를 CI로 작성해줘'))
        self.assertTrue(is_ci_conversion_request('Create CI from the attached PI'))
        self.assertTrue(is_ci_conversion_request('Make a commercial invoice from this proforma invoice'))
        self.assertFalse(is_ci_conversion_request('Create a PI for Dear Glow'))

    def test_short_banking_and_payment_labels_never_reach_ci_remarks(self):
        from Quotation_KEKOREA.agent.renderers import document_lines
        for note in ('Beneficiary: TEST COMPANY; Bank: TEST BANK; A/C: 12345; T/T 100% in advance',
                     'Payment: TEST PAYMENT', '은행: TEST BANK / 계좌: 12345', 'IBAN: TEST123'):
            doc = pi_source()
            doc['remarks'] = note
            prepare_ci_import(doc, requested_type='CI', has_attachments=True)
            self.assertEqual(doc['remarks'], 'N/A')
            self.assertFalse(any(note in line for line in document_lines(ci_render_data(validate_and_calculate(doc)))))

    def test_unsupported_zero_and_nonzero_prices_remain_blocked_by_source_quote_guard(self):
        from Quotation_KEKOREA.agent.extractor import verify_item_quotes
        for price, source in (('0', 'Test Toner 10 PCS'), ('0', 'Test Toner 0 PCS USD 9.00'), ('999', 'Test Toner 10 PCS USD 2.00')):
            doc = pi_source()
            doc.update(source_total=None)
            doc['items'][0].update(unit_price=price, discount_percent='0', source=source, source_line_total=None)
            prepare_ci_import(doc, requested_type='CI', has_attachments=True)
            verify_item_quotes(doc, 'Use attached PI as source for CI', image_context=True)
            result = validate_and_calculate(doc)
            self.assertTrue(ci_import_issues(result))

    def test_derived_shipping_and_omitted_zero_discount_do_not_require_duplicate_printed_values(self):
        from Quotation_KEKOREA.agent.extractor import verify_item_quotes
        doc = pi_source()
        doc['source_total'] = '20.00'
        doc['items'][0].update(free_quantity='3', shipped_quantity='13', discount_percent='0',
                               source_line_total='20.00', source='Test Toner 10 + 3 FOC PCS USD 2.00 20.00')
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        verify_item_quotes(doc, 'Use attached PI as source for CI', image_context=True)
        apply_document_prices(doc, {})
        self.assertEqual(ci_import_issues(validate_and_calculate(doc)), [])

    def test_currency_conflicts_remain_even_when_bank_is_mentioned(self):
        doc = pi_source()
        note = 'Currency is ambiguous because bank currency differs from invoice currency'
        doc['conflicts'] = [note]
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        self.assertTrue(any('currency' in s.lower() for s in doc['conflicts']))
