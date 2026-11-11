"""첨부 PI → CI 가져오기 pytest(원본 tests/test_ci_pi_import.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_ci_pi_import.py
- 원본의 실제 매입가는 가상 값 8000으로, 거래처·브랜드 이름은 가상 값(Acme Supplier·
  Acme Buyer)으로 바꿨다(이식 규칙: 회사 고유 값 금지).
- 원본 seed의 'brand' 키는 계약 15.4절이 카탈로그에서 없애므로 이식본 카탈로그에는 없다.
- `validate_and_calculate`는 발행사 키 `issuer_key`(계약 15.4절)를 받는다(가상 발행사).
- `render_files`는 직인 파일 경로 대신 PNG bytes를 받는다(계약 15.4절 pi_pdf 행).
"""
import copy
import struct
import tempfile
import zlib
from pathlib import Path
from zipfile import ZipFile

from app.trade.ci.imports import (
    apply_document_prices,
    ci_import_issues,
    ci_render_data,
    is_ci_conversion_request,
    prepare_ci_import,
)
from app.trade.common.renderers import document_lines, render_files
from app.trade.common.trade_documents import validate_and_calculate
from app.trade.common.verify_quotes import verify_item_quotes

ISSUER_NAME = "Testworks Trading Co"
ISSUER_KEY = "testworkstrading"


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


def pi_source():
    doc = order()
    doc.update(source_document_type='PI', source_total='18.00', payment_terms='TT TEST PAYMENT',
               bank_details={'account': 'TEST ACCOUNT'}, remarks='BANK INFORMATION: TEST BANK',
               product_family='cosmetics')
    doc['items'][0].update(discount_percent='10', source='Test Toner 10 PCS USD 2.00 10% 18.00',
                           source_line_total='18.00')
    return doc


def synthetic_seal(directory):
    def chunk(kind, body):
        return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body) & 0xffffffff)
    seal = Path(directory) / 'synthetic-seal.png'
    seal.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))
    return seal.read_bytes()


def test_import_keeps_rows_parties_currency_and_terms_but_excludes_payment_data():
    doc = pi_source()
    rows, buyer = copy.deepcopy(doc['items']), copy.deepcopy(doc['buyer'])
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    assert doc['_ci_from_pi'] is True
    assert doc['document_type'] == 'CI'
    assert doc['buyer'] == buyer
    for key in ('product_name', 'quantity', 'unit_price', 'discount_percent'):
        assert doc['items'][0][key] == rows[0][key]
    assert doc['payment_terms'] == 'N/A'
    assert 'bank_details' not in doc
    assert doc['remarks'] == 'N/A'


def test_catalog_refresh_never_changes_prices_on_imported_pi():
    doc = pi_source()
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    seed = {'products': [{'id': 'p1', 'item_name': 'Test Toner'}],
            'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'ACME_BUYER', 'currency': 'USD', 'unit_price': '99'}]}
    apply_document_prices(doc, seed)
    assert doc['items'][0]['unit_price'] == '2'
    assert doc['items'][0]['discount_percent'] == '10'
    result = calculate(doc)
    assert result['total'] == '18.00'
    assert ci_import_issues(result) == []


def test_import_defaults_omitted_discount_to_zero_when_source_has_no_discount_evidence():
    doc = pi_source()
    doc.update(source_total='20.00')
    doc['items'][0].update(discount_percent=None, source_line_total='20.00',
                           source='Test Toner 10 PCS USD 2.00 20.00')
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    assert doc['items'][0]['discount_percent'] == '0'
    result = calculate(doc)
    assert not any('discount' in issue.lower() for issue in result['blocking_issues'])
    assert ci_import_issues(result) == []


def test_import_clears_only_missing_notices_for_fields_filled_during_review():
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
    assert doc['missing_fields'] == ['HS codes']


def test_import_keeps_missing_party_and_document_notices_until_fields_are_filled():
    doc = pi_source()
    doc['document_number'] = None
    doc['buyer'].update(legal_name=None, address=None)
    doc['missing_fields'] = ['Buyer legal name and address: buyer not explicit.',
                             'Commercial invoice number']
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    assert doc['missing_fields'] == ['Buyer legal name and address: buyer not explicit.',
                                     'Commercial invoice number']


def test_import_keeps_discount_review_when_source_mentions_discount_but_rate_is_missing():
    doc = pi_source()
    doc['items'][0].update(discount_percent=None,
                           source='Test Toner 10 PCS USD 2.00 discount 18.00')
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    assert doc['items'][0]['discount_percent'] is None
    result = calculate(doc)
    assert any('Confirm discount percentage' in issue for issue in result['blocking_issues'])
    assert any('discount' in issue.lower() for issue in ci_import_issues(result))


def test_ci_import_matches_product_without_replacing_pi_transaction_price():
    doc = pi_source()
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    item = doc['items'][0]
    seed = {'products': [{'id': 'p1', 'item_name': item['product_name'],
                          'capacity': item.get('capacity')}],
            'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'ACME_BUYER',
                              'currency': 'USD', 'unit_price': '99'}]}
    original_price, original_basis, original_source = (
        item['unit_price'], item['price_basis'], item['price_source'])
    apply_document_prices(doc, seed)
    assert item['product_id'] == 'p1'
    assert item['unit_price'] == original_price
    assert item['price_basis'] == original_basis
    assert item['price_source'] == original_source


def test_ci_without_pi_does_not_use_catalog_price_and_is_blocked():
    doc = order('CI')
    doc['items'][0]['unit_price'] = None
    seed = {'products': [{'id': 'p1', 'item_name': 'Test Toner'}],
            'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'ACME_BUYER',
                              'currency': 'USD', 'unit_price': '99'}]}
    apply_document_prices(doc, seed)
    assert doc['items'][0]['unit_price'] is None
    assert 'CI must be created from an attached PI to use its transaction prices' in ci_import_issues(doc)


def test_pl_matches_product_without_applying_catalog_price():
    doc = order('PL')
    doc['items'][0]['product_name'] = 'Test Toner'
    doc['items'][0]['capacity'] = '150ml'
    doc['items'][0]['unit_price'] = '42'
    seed = {'products': [{'id': 'p1', 'item_name': 'Test Toner', 'capacity': '150ml'}],
            'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ACME_SUPPLIER',
                                 'currency': 'KRW', 'unit_price': '8000'}]}
    apply_document_prices(doc, seed)
    assert doc['items'][0]['product_id'] == 'p1'
    assert doc['items'][0]['unit_price'] == '42'


def test_source_line_and_total_mismatches_are_actionable():
    doc = pi_source()
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    doc['source_total'] = '19.00'
    doc['items'][0]['source_line_total'] = '19.00'
    issues = ci_import_issues(calculate(doc))
    assert any('total' in i.lower() for i in issues)
    assert any('item 1' in i.lower() for i in issues)


def test_imported_zero_price_sample_is_preserved_with_ordinary_positive_price_guard_intact():
    doc = pi_source()
    doc['items'].append(dict(product_name='Trial Toner', quantity='5', paid_quantity='5', unit='PCS',
                             unit_price='0', discount_percent='0', source_line_total='0',
                             source='Trial Toner 5 PCS USD 0.00'))
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    result = calculate(doc)
    assert not result['blocking_issues'], result['blocking_issues']
    assert result['items'][1]['line_total'] == '0.00'
    regular = order('CI')
    regular['items'][0]['unit_price'] = '0'
    assert any('positive number required for unit price' in s
               for s in calculate(regular)['blocking_issues'])


def test_pi_and_po_workflows_remain_unchanged_and_ci_requires_pi():
    for dtype, attached, source in (('PI', True, 'PI'), ('PO', True, 'PI'), ('CI', False, 'PI'), ('CI', True, 'PO')):
        doc = order(dtype)
        doc['source_document_type'] = source
        before = copy.deepcopy(doc)
        prepare_ci_import(doc, requested_type=dtype, has_attachments=attached)
        assert doc == before
        if dtype == 'CI':
            assert 'CI must be created from an attached PI to use its transaction prices' in ci_import_issues(doc)
        else:
            assert ci_import_issues(doc) == []
        assert ci_render_data(doc) == doc


def test_render_adapter_keeps_existing_ci_paid_plus_foc_display_correct_without_mutation():
    doc = pi_source()
    doc['items'][0].update(free_quantity='3', shipped_quantity='13', display_quantity='13')
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    before = copy.deepcopy(doc)
    output = ci_render_data(doc)
    assert output['items'][0]['display_quantity'] == '10'
    assert output['items'][0]['shipped_quantity'] == '13'
    assert doc == before


def test_actual_ci_files_preserve_foc_sample_and_totals_without_pi_bank_or_payment_values(tmp_path):
    doc = pi_source()
    doc['shipment_reference'] = 'TEST-SHIPMENT'
    doc['items'][0].update(free_quantity='3', shipped_quantity='13')
    doc['items'].append(dict(product_name='Trial Toner', quantity='5', paid_quantity='5', unit='PCS',
                             unit_price='0', discount_percent='0', source_line_total='0',
                             source='Trial Toner 5 PCS USD 0.00'))
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    result = calculate(doc)
    assert ci_import_issues(result) == []
    bank = {key: 'DO_NOT_COPY_BANK_VALUE' for key in ('BENEFICIARY', 'BANK_NAME', 'BRANCH', 'SWIFT', 'ACCOUNT_NUMBER', 'BANK_ADDRESS')}
    files = render_files(ci_render_data(result), tmp_path, bank_details=bank, seal=synthetic_seal(tmp_path))
    pdf = files['pdf'].read_bytes()
    assert b'COMMERCIAL INVOICE' in pdf
    assert b'10 + 3 FOC' in pdf, 'CI must show original paid plus FOC quantity'
    assert b'18 PCS' in pdf, 'CI shipping total must include FOC and samples once'
    assert b'Trial Toner' in pdf and b'18.00' in pdf
    with ZipFile(files['xlsx']) as book:
        sheet = book.read('xl/worksheets/sheet1.xml')
    for raw in (pdf, sheet, files['html'].read_bytes()):
        assert b'DO_NOT_COPY_BANK_VALUE' not in raw, 'CI must exclude bank values'
        assert b'TT TEST PAYMENT' not in raw, 'CI must exclude PI payment values'


def test_explicit_conversion_command_is_distinct_from_creating_a_pi():
    assert is_ci_conversion_request('Convert PI to CI')
    assert is_ci_conversion_request('첨부 PI를 CI로 작성해줘')
    assert is_ci_conversion_request('Create CI from the attached PI')
    assert is_ci_conversion_request('Make a commercial invoice from this proforma invoice')
    assert not is_ci_conversion_request('Create a PI for Acme Buyer')


def test_short_banking_and_payment_labels_never_reach_ci_remarks():
    for note in ('Beneficiary: TEST COMPANY; Bank: TEST BANK; A/C: 12345; T/T 100% in advance',
                 'Payment: TEST PAYMENT', '은행: TEST BANK / 계좌: 12345', 'IBAN: TEST123'):
        doc = pi_source()
        doc['remarks'] = note
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        assert doc['remarks'] == 'N/A'
        assert not any(note in line for line in document_lines(ci_render_data(calculate(doc))))


def test_unsupported_zero_and_nonzero_prices_remain_blocked_by_source_quote_guard():
    for price, source in (('0', 'Test Toner 10 PCS'), ('0', 'Test Toner 0 PCS USD 9.00'), ('999', 'Test Toner 10 PCS USD 2.00')):
        doc = pi_source()
        doc.update(source_total=None)
        doc['items'][0].update(unit_price=price, discount_percent='0', source=source, source_line_total=None)
        prepare_ci_import(doc, requested_type='CI', has_attachments=True)
        verify_item_quotes(doc, 'Use attached PI as source for CI', image_context=True)
        result = calculate(doc)
        assert ci_import_issues(result)


def test_derived_shipping_and_omitted_zero_discount_do_not_require_duplicate_printed_values():
    doc = pi_source()
    doc['source_total'] = '20.00'
    doc['items'][0].update(free_quantity='3', shipped_quantity='13', discount_percent='0',
                           source_line_total='20.00', source='Test Toner 10 + 3 FOC PCS USD 2.00 20.00')
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    verify_item_quotes(doc, 'Use attached PI as source for CI', image_context=True)
    apply_document_prices(doc, {})
    assert ci_import_issues(calculate(doc)) == []


def test_currency_conflicts_remain_even_when_bank_is_mentioned():
    doc = pi_source()
    note = 'Currency is ambiguous because bank currency differs from invoice currency'
    doc['conflicts'] = [note]
    prepare_ci_import(doc, requested_type='CI', has_attachments=True)
    assert any('currency' in s.lower() for s in doc['conflicts'])
