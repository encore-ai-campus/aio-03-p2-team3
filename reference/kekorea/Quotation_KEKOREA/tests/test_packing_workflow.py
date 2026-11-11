"""Packing-image data and ECLADO purchase-price regression checks."""
import unittest
from io import BytesIO
from zipfile import ZipFile

from Quotation_KEKOREA.agent.packing import reconcile_packing
from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices
from Quotation_KEKOREA.agent.renderers import _xlsx_bytes
from Quotation_KEKOREA.agent.trade_documents import validate_and_calculate


def packing_example():
    values = [
        ("A", "351128", "PCS", "6", "3511.28", "3660.00", "9.306"),
        ("B", "280", "PCS", "0.5", "2.80", "305.00", "0.776"),
        ("C", "250552", "PCS", "5.5", "2505.52", "3355.00", "8.531"),
        ("D", "750", "PCS", "0.5", "7.50", "305.00", "0.776"),
        ("E", "13291", "PCS", "0.5", "1927.98", "3032.60", "0.644"),
        ("F", "2399.48", "KG", "12", "2399.48", "2759.48", "15.444"),
    ]
    return {"document_type": "PL", "product_family": "solar_cell", "currency": None,
            "seller": {"legal_name": "KE KOREA CO. LTD", "address": "Seoul"},
            "buyer": {"legal_name": "Buyer", "address": "Address"},
            "document_number": "DRAFT", "incoterms": "EXW Cyberjaya", "shipment_reference": "Reference",
            "actual_package_count": "25", "container_count": None,
            "declared_total_quantity": "618400", "declared_total_quantity_unit": "PCS",
            "declared_net_weight_kg": "10354.56", "declared_gross_weight_kg": "13417.08",
            "declared_volume_cbm": "35.475", "hs_code": "8541 42 000", "missing_fields": [], "conflicts": [],
            "items": [{"product_name": n, "quantity": q, "unit": unit, "package_type": "PALLET",
                       "package_count": count, "net_weight_kg": nw, "gross_weight_kg": gw, "volume_cbm": cbm}
                      for n, q, unit, count, nw, gw, cbm in values]}


class PackingWorkflowTests(unittest.TestCase):
    def test_mixed_units_and_supplier_total_mismatches_are_kept_separate(self):
        result = reconcile_packing(packing_example())
        self.assertEqual(result["quantities"], {"PCS": "616001", "KG": "2399.48"})
        self.assertEqual(result["calculated"]["package_count"], "25.0")
        self.assertEqual(result["calculated"]["net_weight_kg"], "10354.56")
        self.assertEqual(result["calculated"]["gross_weight_kg"], "13417.08")
        self.assertEqual(result["calculated"]["volume_cbm"], "35.477")
        self.assertEqual(result["issues"], [])
        self.assertTrue(any("volume (CBM)" in issue for issue in result["discrepancies"]))
        self.assertTrue(any("quantity total" in issue for issue in result["discrepancies"]))

    def test_pl_needs_no_currency_or_prices_and_excel_preserves_packing_columns(self):
        doc = packing_example()
        doc["declared_volume_cbm"] = "35.477"
        doc["declared_total_quantity"] = "616001"
        result = validate_and_calculate(doc)
        self.assertFalse(any("currency" in issue.lower() or "unit price" in issue.lower()
                             for issue in result["blocking_issues"]))
        self.assertFalse(any(issue.startswith("Packing:") for issue in result["blocking_issues"]))
        with ZipFile(BytesIO(_xlsx_bytes(result))) as workbook:
            sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
        for text in ("NW (KG)", "GW (KG)", "CBM", "2399.48", "35.477", "8541 42 000"):
            self.assertIn(text, sheet)

    def test_missing_row_value_is_not_treated_as_zero(self):
        doc = packing_example()
        doc["items"][0]["net_weight_kg"] = None
        self.assertIsNone(reconcile_packing(doc)["calculated"]["net_weight_kg"])

    def test_discrepancies_use_row_totals_without_overwriting_source(self):
        doc = packing_example()
        doc["actual_package_count"] = "26"
        result = validate_and_calculate(doc)
        self.assertEqual(result["declared_volume_cbm"], "35.475")
        self.assertEqual(result["declared_total_quantity"], "618400")
        self.assertFalse(result["ready_for_issue"])
        self.assertTrue(any("Packing source discrepancy" in issue for issue in result["blocking_issues"]))
        with ZipFile(BytesIO(_xlsx_bytes(result))) as workbook:
            sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("35.477", sheet)
        self.assertIn('>25</t>', sheet)
        self.assertIn("616,001", sheet)
        self.assertIn("2,399.48", sheet)
        self.assertNotIn("35.475", sheet)

    def test_invalid_values_and_mixed_package_types_need_review(self):
        doc = packing_example()
        doc["items"][0]["gross_weight_kg"] = "1,2"
        doc["items"][1]["package_type"] = "BOX"
        issues = reconcile_packing(doc)["issues"]
        self.assertTrue(any("gross weight is invalid" in issue for issue in issues))
        self.assertTrue(any("different package types" in issue for issue in issues))

    def test_missing_or_mismatched_po_seller_does_not_block_eclado_catalog_price(self):
        seed = {"products": [{"id": "p1", "brand": "ECLADO", "item_name": "Toner", "capacity": "150ml"}],
                "purchase_prices": [{"product_id": "p1", "supplier_key": "ECLADO", "currency": "KRW", "unit_price": "8000", "source_row": 31}],
                "buyer_prices": []}
        draft = {"document_type": "PO", "product_family": "cosmetics", "currency": None,
                 "seller": {}, "items": [{"product_name": "Toner", "capacity": "150ml", "source": "Toner 150ml"}]}
        apply_verified_eclado_prices(draft, seed)
        self.assertEqual(draft["currency"], "KRW")
        self.assertEqual(draft["items"][0]["unit_price"], "8000")
        self.assertFalse(draft["pending_confirmations"])
        self.assertFalse(draft["seller"].get("legal_name"))
        draft["seller"] = {"legal_name": "Different Supplier"}
        apply_verified_eclado_prices(draft, seed)
        self.assertEqual(draft["items"][0]["unit_price"], "8000")
        self.assertEqual(draft["currency"], "KRW")
        self.assertFalse(draft["pending_confirmations"])


if __name__ == "__main__":
    unittest.main()
