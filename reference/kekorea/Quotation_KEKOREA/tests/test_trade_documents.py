"""Synthetic checks for English trade document drafts and safe calculations."""
import importlib.util
from decimal import Decimal
from pathlib import Path
import zipfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("trade_documents", ROOT / "agent" / "trade_documents.py")
trade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trade)
from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices, load_local_seed, match_eclado_product, resolve_price
from Quotation_KEKOREA.agent.renderers import amount_in_english, document_lines, render_files, _pdf_bytes, _xlsx_bytes


def sample_trade(**updates):
    data = {
        "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul", "contact": None, "phone": None, "email": None},
        "seller": {"legal_name": "KE KOREA CO. LTD", "address": None, "contact": None, "phone": None, "email": None},
        "items": [{"product_name": "Example Toner", "capacity": "100 ml", "quantity": "10", "unit": "PCS", "unit_price": "12.50", "price_basis": "per PCS", "discount_percent": "10", "paid_quantity": "10", "free_quantity": "0", "shipped_quantity": "10", "source": "synthetic test"}],
        "incoterms": None, "payment_terms": None, "remarks": None, "document_number": None,
        "issue_date": "2026-10-30", "ship_to": None, "bill_to": None,
        "missing_fields": [], "conflicts": [], "source_notes": ["synthetic test"],
    }
    data.update(updates)
    return data


class TradeDocumentTests(unittest.TestCase):
    def test_explicit_zero_quantity_is_valid_and_kept_in_every_document_type(self):
        for dtype in ('PI', 'PO', 'CI', 'PL'):
            for zero in ('0', '0.0', 0):
                with self.subTest(dtype=dtype, zero=zero):
                    doc = sample_trade(document_type=dtype)
                    doc['items'][0].update(quantity=zero, paid_quantity=zero, shipped_quantity=zero)
                    result = trade.validate_and_calculate(doc)
                    self.assertFalse(any('paid quantity' in issue for issue in result['blocking_issues']))
                    self.assertEqual(Decimal(result['items'][0]['quantity']), 0)
                    self.assertEqual(result['items'][0]['line_total'], '0.00')
                    self.assertEqual(result['total'], '0.00')
                    self.assertEqual(len(result['items']), 1)

    def test_missing_negative_and_nonfinite_quantities_remain_invalid(self):
        for value in (None, '', '-1', 'invalid', 'NaN', 'Infinity'):
            with self.subTest(value=value):
                doc = sample_trade()
                doc['items'][0].update(quantity=value, paid_quantity=value, shipped_quantity=value)
                result = trade.validate_and_calculate(doc)
                self.assertTrue(any('paid quantity' in issue for issue in result['blocking_issues']))

    def test_image_quantity_total_includes_zero_row_without_blocking_calculation(self):
        quantities = [10, 15, 23, 20, 30, 405, 0, 10, 20, 30, 40, 50, 60, 70, 70, 40,
                      320, 10, 2040, 20, 10, 10, 20, 20]
        doc = sample_trade(product_family='other')
        template = doc['items'][0]
        doc['items'] = [{**template, 'quantity': str(qty), 'paid_quantity': str(qty),
                         'shipped_quantity': str(qty), 'unit_price': '1', 'discount_percent': '0'}
                        for qty in quantities]
        result = trade.validate_and_calculate(doc)
        self.assertFalse(any('paid quantity' in issue for issue in result['blocking_issues']))
        self.assertEqual(sum(Decimal(item['quantity']) for item in result['items']), 3343)
        self.assertEqual(result['total'], '3343.00')

    def test_decimal_discount_is_applied_once_to_final_unit_price(self):
        result = trade.validate_and_calculate(sample_trade())
        item = result["items"][0]
        self.assertEqual(item["final_unit_price"], "11.25")
        self.assertEqual(item["line_total"], "112.50")
        self.assertEqual(result["total"], "112.50")

    def test_missing_transaction_terms_block_document_render(self):
        result = trade.validate_and_calculate(sample_trade())
        self.assertIn("Incoterms and named place", result["blocking_issues"])
        self.assertFalse(result["ready_for_issue"])

    def test_conflicting_or_unknown_price_basis_blocks_document(self):
        data = sample_trade(product_family="solar")
        data["items"][0]["price_basis"] = None
        result = trade.validate_and_calculate(data)
        self.assertIn("Price basis for Example Toner", result["blocking_issues"])

    def test_promotion_separates_paid_free_and_shipped_quantities(self):
        item = trade.apply_promotion("5", "2+1")
        self.assertEqual(item, {"paid_quantity": "5", "free_quantity": "2", "shipped_quantity": "7"})

    def test_free_items_are_not_charged(self):
        data = sample_trade()
        data["items"][0].update({"quantity": "5", "paid_quantity": "5", "free_quantity": "2", "shipped_quantity": "7"})
        result = trade.validate_and_calculate(data)
        self.assertEqual(result["items"][0]["line_total"], "56.25")

    def test_non_english_document_fields_are_rejected(self):
        data = sample_trade()
        data["buyer"]["legal_name"] = "가상의 구매자"
        result = trade.validate_and_calculate(data)
        self.assertIn("Buyer legal name must be English", result["blocking_issues"])

    def test_chinese_company_name_and_address_require_original_plus_english(self):
        data = sample_trade()
        data["buyer"]["legal_name"] = "华星贸易有限公司"
        data["buyer"]["address"] = "上海市浦东新区"
        result = trade.validate_and_calculate(data)
        self.assertIn("Buyer Chinese legal name must include its English translation in parentheses", result["blocking_issues"])
        self.assertIn("Buyer Chinese address must include its English translation in parentheses", result["blocking_issues"])

    def test_chinese_company_name_and_address_with_english_translation_are_allowed(self):
        data = sample_trade()
        data["buyer"]["legal_name"] = "华星贸易有限公司 (Huaxing Trading Co., Ltd.)"
        data["buyer"]["address"] = "上海市浦东新区 (Pudong New Area, Shanghai)"
        result = trade.validate_and_calculate(data)
        self.assertNotIn("Buyer Chinese legal name must include its English translation in parentheses", result["blocking_issues"])
        self.assertNotIn("Buyer Chinese address must include its English translation in parentheses", result["blocking_issues"])

    def test_chinese_remarks_must_be_translated_to_english_only(self):
        data = sample_trade(remarks="尽快发货")
        result = trade.validate_and_calculate(data)
        self.assertIn("Remarks must be translated into English", result["blocking_issues"])

    def test_chinese_company_name_is_preserved_in_review_files(self):
        data = sample_trade()
        data["buyer"]["legal_name"] = "华星贸易有限公司 (Huaxing Trading Co., Ltd.)"
        data["buyer"]["address"] = "上海市浦东新区 (Pudong New Area, Shanghai)"
        result = trade.validate_and_calculate(data)
        pdf = _pdf_bytes(document_lines(result))
        self.assertIn("华星贸易有限公司".encode("utf-16-be").hex().upper().encode(), pdf)
        with zipfile.ZipFile(__import__("io").BytesIO(_xlsx_bytes(result))) as workbook:
            self.assertIn("华星贸易有限公司".encode("utf-8"), workbook.read("xl/worksheets/sheet1.xml"))

    def test_po_and_pi_party_roles_are_checked(self):
        data = sample_trade(document_type="PO")
        self.assertIn("PO seller must be the supplier and buyer must be KE KOREA", trade.validate_and_calculate(data)["blocking_issues"])

    def test_unconfirmed_packing_cannot_be_finalized(self):
        data = sample_trade(document_type="PL")
        data["packages"] = []
        self.assertIn("Actual package count and weights", trade.validate_and_calculate(data)["blocking_issues"])

    def test_eclado_local_seed_has_separate_purchase_and_buyer_price_tables(self):
        seed = load_local_seed()
        self.assertEqual(len(seed["products"]), 157)
        product = seed["products"][0]
        self.assertEqual(match_eclado_product(product["item_name"], product.get("capacity"), seed["products"])["status"], "matched")
        role = "purchase" if product["kind"] == "sample" else "sale"
        currency = "KRW" if role == "purchase" or product["kind"] == "sample" else "USD"
        self.assertIsNotNone(resolve_price(product["id"], seed, role, currency))

    def test_dear_glow_price_is_not_applied_to_an_unregistered_buyer(self):
        seed = load_local_seed()
        product = next(p for p in seed["products"] if p["kind"] == "standard")
        draft = {"document_type": "PI", "product_family": "cosmetics", "currency": "USD",
                 "buyer": {"legal_name": "Different Buyer Ltd"}, "items": [{
                     "product_name": product["item_name"], "capacity": product["capacity"],
                     "unit_price": None, "source": None}]}
        apply_verified_eclado_prices(draft, seed)
        self.assertIsNot(draft["items"][0].get("master_price"), True)
        self.assertTrue(any("local catalog price is only for DEAR GLOW" in issue for issue in draft["missing_fields"]))

    def test_purchase_and_sale_prices_are_selected_by_document_direction(self):
        seed = load_local_seed()
        product = next(p for p in seed["products"] if p["kind"] == "standard")
        item = {"product_name": product["item_name"], "capacity": product["capacity"],
                "unit_price": None, "source": None}
        pi = {"document_type": "PI", "product_family": "cosmetics", "currency": "USD",
              "buyer": {"legal_name": "Dear Glow"}, "items": [dict(item)]}
        po = {"document_type": "PO", "product_family": "cosmetics", "currency": "KRW",
              "seller": {"legal_name": "Eclado Co., Ltd."}, "items": [dict(item)]}
        apply_verified_eclado_prices(pi, seed)
        apply_verified_eclado_prices(po, seed)
        self.assertEqual(pi["items"][0]["price_source"].split(";")[0], "Verified ECLADO catalog")
        self.assertEqual(po["items"][0]["price_source"].split(";")[0], "Verified ECLADO catalog")
        self.assertEqual(pi["currency"], "USD")
        self.assertEqual(po["currency"], "KRW")

    def test_amount_words(self):
        self.assertEqual(amount_in_english("112.50", "USD"), "ONE HUNDRED TWELVE US DOLLARS AND FIFTY CENTS ONLY")

    def test_generated_review_files_are_readable_containers(self):
        import struct
        import zlib
        from uuid import uuid4
        data = trade.validate_and_calculate(sample_trade())
        temp = ROOT / "outputs"
        temp.mkdir(parents=True, exist_ok=True)
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
        # A disposable RGB image of sufficient size exercises the required seal
        # without depending on a private company asset in the test environment.
        width, height = 900, 300
        pixels = (b"\0" + b"\xff" * (width * 3)) * height
        seal = temp / f"test-seal-{uuid4().hex}.png"
        seal.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
                         chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))
        paths = {}
        try:
            paths = render_files(data, temp, seal_path=seal)
            self.assertTrue(paths["pdf"].read_bytes().startswith(b"%PDF-1.4"))
            with zipfile.ZipFile(paths["xlsx"]) as workbook:
                self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
                sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
                self.assertIn("112.50", sheet)
                self.assertEqual(workbook.read("xl/media/seal.png"), seal.read_bytes())
            self.assertIn("AMOUNT IN WORDS", paths["html"].read_text(encoding="utf-8"))
        finally:
            for path in paths.values():
                path.unlink(missing_ok=True)
            seal.unlink(missing_ok=True)

    def test_renderer_rejects_non_english_document_text_instead_of_corrupting_it(self):
        data = trade.validate_and_calculate(sample_trade())
        data["buyer"]["legal_name"] = "구매자"
        with self.assertRaisesRegex(ValueError, "English or Latin-1"):
            from Quotation_KEKOREA.agent.renderers import document_lines
            document_lines(data)


if __name__ == "__main__":
    unittest.main()
