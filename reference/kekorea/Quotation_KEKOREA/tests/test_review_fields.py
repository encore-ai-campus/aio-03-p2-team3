"""Missing document values must be completed explicitly before downloading."""
import unittest

from Quotation_KEKOREA.agent.review_fields import missing_review_fields, apply_review_value


def complete_draft():
    party = {"legal_name": "Company", "address": "Address", "contact": "N/A", "phone": "N/A", "email": "N/A"}
    return {"document_type": "PI", "currency": "USD", "document_number": "DRAFT",
            "buyer": dict(party), "seller": dict(party), "incoterms": "EXW Seoul",
            "payment_terms": "Advance payment", "ship_to": "N/A", "country_of_origin": "Korea",
            "shipment_reference": "N/A", "items": [{"product_name": "Cell", "quantity": "10",
                "paid_quantity": "10", "unit": "PCS", "unit_price": "1", "discount_percent": "0"}]}


class ReviewFieldsTests(unittest.TestCase):
    def test_entering_missing_discount_resolves_only_the_ambiguous_discount_request(self):
        doc = complete_draft()
        doc['items'][0]['discount_percent'] = None
        doc['conflicts'] = ['Discount was mentioned without a percentage; specify a single discount rate.',
                            'Unverified source price']
        apply_review_value(doc, missing_review_fields(doc)[0], '0')
        self.assertEqual(doc['conflicts'], ['Unverified source price'])

    def test_catalog_refresh_after_entering_buyer_removes_only_obsolete_catalog_warnings(self):
        from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices
        doc = complete_draft()
        doc['product_family'] = 'cosmetics'
        doc['buyer']['legal_name'] = None
        doc['items'][0].update(product_name='Sample Cream', capacity='50 ml', unit_price=None)
        doc['missing_fields'] = ['Unverified tax code']
        seed = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Sample Cream', 'capacity': '50 ml'}],
                'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW', 'currency': 'USD', 'unit_price': '10'}]}
        apply_verified_eclado_prices(doc, seed)
        self.assertTrue(any('transaction-specific' in field for field in doc['missing_fields']))
        field = next(field for field in missing_review_fields(doc) if field.path == ('buyer', 'legal_name'))
        apply_review_value(doc, field, 'Dear Glow')
        apply_verified_eclado_prices(doc, seed)
        self.assertEqual(doc['items'][0]['unit_price'], '10')
        self.assertEqual(doc['missing_fields'], ['Unverified tax code'])

    def test_missing_terms_and_party_contact_have_editable_paths(self):
        doc = complete_draft()
        doc['items'][0]['discount_percent'] = 0
        doc['incoterms'] = 'TO BE CONFIRMED'
        doc['payment_terms'] = None
        doc['buyer']['email'] = 'Not provided'
        paths = {field.path for field in missing_review_fields(doc)}
        self.assertEqual(paths, {('incoterms',), ('payment_terms',), ('buyer', 'email')})

    def test_explicit_na_is_optional_only_and_zero_discount_is_valid(self):
        doc = complete_draft()
        self.assertEqual(missing_review_fields(doc), [])
        doc['buyer']['legal_name'] = 'N/A'
        self.assertIn(('buyer', 'legal_name'), {field.path for field in missing_review_fields(doc)})

    def test_completion_changes_document_values_without_dropping_unrelated_missing_evidence(self):
        doc = complete_draft()
        doc['payment_terms'] = None
        doc['missing_fields'] = ['payment_terms', 'Unverified supplier tax code']
        field = missing_review_fields(doc)[0]
        apply_review_value(doc, field, '30% deposit, balance before shipment')
        self.assertEqual(doc['payment_terms'], '30% deposit, balance before shipment')
        self.assertEqual(doc['missing_fields'], ['Unverified supplier tax code'])
        self.assertEqual(missing_review_fields(doc), [])

    def test_missing_product_and_price_are_editable_but_catalog_confirmation_is_not_invented(self):
        doc = complete_draft()
        doc['items'][0].update(product_name=None, unit_price=None, discount_percent=None)
        fields = {field.path: field for field in missing_review_fields(doc)}
        self.assertIn(('items', 0, 'product_name'), fields)
        apply_review_value(doc, fields[('items', 0, 'unit_price')], '2')
        self.assertEqual(doc['items'][0]['unit_price'], '2')
        self.assertNotIn('price_override_confirmed', doc['items'][0])

    def test_pl_has_no_currency_or_price_requirement(self):
        doc = complete_draft()
        doc['document_type'] = 'PL'
        doc['currency'] = None
        doc['payment_terms'] = 'N/A'
        doc['shipment_reference'] = 'TEST'
        doc['container_count'] = '0'
        doc['items'][0]['unit_price'] = None
        self.assertEqual(missing_review_fields(doc), [])
