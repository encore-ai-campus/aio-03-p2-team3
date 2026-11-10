"""Mocked REST integration tests; no Supabase requests or real credentials are used."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("catalog_pricing", ROOT / "agent" / "pricing.py")
pricing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pricing)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class SupabaseCatalogTests(unittest.TestCase):
    def test_eclado_supplier_aliases_share_the_verified_purchase_profile(self):
        catalog = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
                   'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ECLADO', 'currency': 'KRW',
                                        'unit_price': '1000', 'source_row': 1}]}
        aliases = ('eclado', 'ECLADO', 'ECLADO CO. LTD', 'e C l A d O Co., Ltd.',
                   '에끌라도', '에끌라두', '주식회사 에 끌 라 도', '에 끌 라 두 주식회사', 'ＥＣＬＡＤＯ')
        for name in aliases:
            with self.subTest(supplier=name):
                draft = {'document_type': 'PO', 'product_family': 'other', 'currency': None,
                         'seller': {'legal_name': name},
                         'items': [{'product_name': 'Test Cream', 'capacity': '50 ml', 'unit': 'PCS'}]}
                pricing.apply_verified_eclado_prices(draft, catalog)
                self.assertEqual(draft['currency'], 'KRW')
                self.assertEqual(draft['items'][0].get('unit_price'), '1000')
                self.assertEqual(draft['items'][0].get('price_basis'), 'PCS')
                self.assertTrue(draft['items'][0]['master_price'])
                self.assertEqual(draft['seller']['legal_name'], name)
                self.assertEqual(draft.get('pending_confirmations'), [])

    def test_recognized_supplier_loads_matching_rows_even_if_one_product_is_unmatched(self):
        catalog = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
                   'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ECLADO', 'currency': 'KRW',
                                        'unit_price': '1000', 'source_row': 1}]}
        draft = {'document_type': 'PO', 'product_family': 'other', 'currency': None,
                 'seller': {'legal_name': 'ECLADO CO. LTD'},
                 'items': [{'product_name': 'Test Cream', 'capacity': '50 ml'},
                           {'product_name': 'Unconfirmed Product', 'capacity': '10 ml'}]}
        pricing.apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['product_family'], 'cosmetics')
        self.assertEqual(draft['currency'], 'KRW')
        self.assertEqual(draft['items'][0].get('unit_price'), '1000')
        self.assertIsNone(draft['items'][1].get('unit_price'))
        self.assertTrue(any('Unconfirmed Product' in entry for entry in draft['missing_fields']))

    def test_po_uses_eclado_purchase_price_even_when_source_pi_names_ke_korea_as_seller(self):
        catalog = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
                   'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ECLADO', 'currency': 'KRW',
                                        'unit_price': '1000', 'source_row': 1}]}
        draft = {'document_type': 'PO', 'product_family': 'cosmetics', 'currency': 'USD',
                 'seller': {'legal_name': 'KE KOREA CO. LTD', 'address': 'Supplier address'},
                 'buyer': {'legal_name': 'KE KOREA CO. LTD', 'address': 'Buyer address'},
                 'missing_fields': ['PO buyer legal name and address',
                                    'ECLADO supplier legal name and address'],
                 'items': [{'product_name': 'Test Cream', 'capacity': '50 ml',
                            'unit': 'PCS', 'unit_price': '10.25', 'price_basis': 'USD/PCS',
                            'source': 'USD 10.25 per PCS'}]}
        pricing.apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['currency'], 'KRW')
        self.assertEqual(draft['items'][0].get('unit_price'), '1000')
        self.assertEqual(draft['items'][0].get('price_basis'), 'PCS')
        self.assertEqual(draft['items'][0].get('price_source'),
                         'Verified ECLADO catalog; source workbook row 1')
        self.assertTrue(draft['items'][0]['master_price'])
        self.assertFalse(draft['conflicts'])
        self.assertEqual(draft['missing_fields'], [])
        self.assertEqual(draft.get('pending_confirmations'), [])

    def test_loads_one_consistent_catalog_snapshot_using_server_secret_apikey(self):
        product = {"id": "product-1", "brand": "ECLADO", "kind": "standard",
                   "item_name": "Sample Cream", "capacity": "50 ml"}
        replies = [
            [{"id": "import-1", "imported_at": "2026-10-30T00:00:00Z"}],
            [product],
            [{"id": "purchase-1", "import_id": "import-1", "product_id": "product-1",
              "supplier_key": "ECLADO", "currency": "KRW", "unit_price": "1000", "source_row": 4}],
            [{"id": "sale-1", "import_id": "import-1", "product_id": "product-1",
              "buyer_key": "DEAR_GLOW", "currency": "USD", "unit_price": "10.25", "source_row": 4}],
        ]
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(replies[len(requests) - 1])
        result = pricing.load_supabase_catalog({
            "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "secret-test-value"
        }, opener=opener)
        self.assertEqual(len(result["products"]), 1)
        self.assertEqual(result["import"]["id"], "import-1")
        self.assertEqual(result["buyer_prices"][0]["unit_price"], "10.25")
        self.assertEqual(len(requests), 4)
        for request in requests:
            self.assertEqual(request.get_header("Apikey"), "secret-test-value")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertNotIn("secret-test-value", request.full_url)
        self.assertIn("order=imported_at.desc", requests[0].full_url)
        self.assertTrue(all("import_id=eq.import-1" in request.full_url for request in requests[2:]))

    def test_requires_server_secret_not_publishable_key(self):
        with self.assertRaisesRegex(ValueError, "SUPABASE_SECRET_KEY"):
            pricing.load_supabase_catalog({"SUPABASE_URL": "https://example.supabase.co",
                                          "SUPABASE_PUBLISHABLE_KEY": "public-test"})

    def test_rejects_project_url_that_is_not_https_supabase(self):
        with self.assertRaisesRegex(ValueError, "SUPABASE_URL"):
            pricing.load_supabase_catalog({"SUPABASE_URL": "http://localhost", "SUPABASE_SECRET_KEY": "x"})

    def test_loaded_supabase_prices_feed_the_existing_exact_match_price_resolver(self):
        from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices
        catalog = {
            "products": [{"id": "product-1", "brand": "ECLADO", "kind": "standard",
                          "item_name": "Sample Cream", "capacity": "50 ml"}],
            "purchase_prices": [],
            "buyer_prices": [{"id": "sale-1", "product_id": "product-1", "buyer_key": "DEAR_GLOW",
                              "currency": "USD", "unit_price": "10.25", "source_row": 7}],
        }
        draft = {"document_type": "PI", "product_family": "cosmetics", "currency": "USD",
                 "buyer": {"legal_name": "Dear Glow"}, "items": [{"product_name": "Sample Cream",
                 "capacity": "50 ml", "unit_price": None, "source": None}]}
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft["items"][0]["unit_price"], "10.25")
        self.assertIs(draft["items"][0]["master_price"], True)

    def test_http_error_is_sanitized(self):
        import urllib.error
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as context:
            pricing.load_supabase_catalog({"SUPABASE_URL": "https://example.supabase.co",
                                           "SUPABASE_SECRET_KEY": "secret-test-value"}, opener=opener)
        self.assertNotIn("secret-test-value", str(context.exception))

    def test_zero_quantity_po_uses_purchase_prices_without_mixing_sale_currency(self):
        from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices
        from Quotation_KEKOREA.agent.trade_documents import validate_and_calculate
        catalog = {'products': [{'id': 'p1', 'brand': 'ECLADO', 'item_name': 'Test Cream', 'capacity': '50 ml'}],
                   'purchase_prices': [{'product_id': 'p1', 'supplier_key': 'ECLADO', 'currency': 'KRW',
                                        'unit_price': '1000', 'source_row': 1}],
                   'buyer_prices': [{'product_id': 'p1', 'buyer_key': 'DEAR_GLOW', 'currency': 'USD',
                                     'unit_price': '10', 'source_row': 1}]}
        draft = {'document_type': 'PO', 'product_family': 'cosmetics', 'currency': None,
                 'seller': {'legal_name': 'ECLADO'}, 'buyer': {'legal_name': 'KE KOREA CO. LTD'},
                 'items': [{'product_name': 'Test Cream', 'capacity': '50 ml', 'quantity': str(qty),
                            'paid_quantity': str(qty), 'shipped_quantity': str(qty), 'unit': 'PCS',
                            'price_basis': 'USD/PCS',
                            'discount_percent': '0'} for qty in (0, 5)]}
        apply_verified_eclado_prices(draft, catalog)
        result = validate_and_calculate(draft)
        self.assertEqual(result['currency'], 'KRW')
        self.assertEqual(result['total'], '5000')
        self.assertEqual(result['items'][0]['line_total'], '0')
        self.assertTrue(all(item['master_price'] and item['unit_price'] == '1000' for item in result['items']))
        self.assertTrue(all(item['price_basis'] == 'PCS' for item in result['items']))
        self.assertFalse(any('number required' in issue for issue in result['blocking_issues']))
        draft['currency'] = 'USD'
        for item in draft['items']:
            item['unit_price'] = '10'
            item['source'] = 'USD 10 per PCS'
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['currency'], 'KRW')
        self.assertTrue(all(item['unit_price'] == '1000' for item in draft['items']))
        self.assertFalse(any('Verified USD catalog price' in issue for issue in draft['missing_fields']))


if __name__ == "__main__":
    unittest.main()
