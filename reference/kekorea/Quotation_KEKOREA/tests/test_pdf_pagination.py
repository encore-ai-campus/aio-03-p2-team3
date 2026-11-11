"""Use available product space while keeping the closing panels together."""
import re
import struct
import tempfile
from pathlib import Path
import unittest
import zlib

from Quotation_KEKOREA.agent.pi_pdf import _paginate_rows, render_trade_document


class PdfPaginationTests(unittest.TestCase):
    def test_all_products_stay_on_first_page_when_only_closing_panels_overflow(self):
        rows = [{"height": 13.5, "name": str(i)} for i in range(20)]
        pages = _paginate_rows(rows, 310, 40, False)
        self.assertEqual(pages, [rows, []])

    def test_rows_move_only_when_the_next_row_exceeds_available_space(self):
        rows = [{"height": 13.5, "name": str(i)} for i in range(100)]
        pages = _paginate_rows(rows, 310, 40, False)
        self.assertEqual([len(page) for page in pages], [31, 42, 27])
        self.assertEqual([row for page in pages for row in page], rows)

    def test_exact_fit_and_tall_wrapped_rows_preserve_order(self):
        rows = [{"height": 425}, {"height": 400}]
        self.assertEqual(_paginate_rows(rows, 310, 40, False), [[rows[0]], [rows[1]], []])

    def test_packing_list_also_keeps_all_fitting_products_on_first_page(self):
        rows = [{"height": 13.5} for _ in range(20)]
        self.assertEqual(_paginate_rows(rows, 310, 40, True), [rows, []])

    def test_small_document_keeps_products_and_closing_panels_on_one_page(self):
        rows = [{"height": 13.5}]
        self.assertEqual(_paginate_rows(rows, 310, 40, False), [rows])

    def test_pdf_does_not_move_last_product_or_split_bank_and_seal_panels(self):
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

        with tempfile.TemporaryDirectory() as directory:
            seal = Path(directory) / "seal.png"
            seal.write_bytes(b"\x89PNG\r\n\x1a\n" +
                             chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
                             chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))
            doc = {"document_type": "PI", "currency": "USD", "remarks": "N/A", "total": "200",
                   "seller": {"legal_name": "Test Seller"}, "buyer": {"legal_name": "Test Buyer"},
                   "items": [{"product_name": f"Product-{i:02}", "quantity": "10", "unit": "PCS",
                              "unit_price": "1", "line_total": "10"} for i in range(20)]}
            bank = {key: f"TEST_{key}" for key in ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT",
                                                    "ACCOUNT_NUMBER", "BANK_ADDRESS")}
            pdf = render_trade_document(doc, bank, seal_path=seal)
            streams = re.findall(rb"stream\n(.*?)endstream", pdf, re.S)
            pages = [stream for stream in streams if b"DRAFT - NOT FOR ISSUE" in stream]
            self.assertEqual(len(pages), 2)
            self.assertIn(b"Product-19", pages[0])
            self.assertNotIn(b"Product-19", pages[1])
            self.assertNotIn(b"PRODUCT & PRICING", pages[1])
            for label in (b"BENEFICIARY", b"BANK NAME", b"BRANCH NAME", b"SWIFT CODE",
                          b"ACCOUNT NUMBER", b"BANK ADDRESS", b"AUTHORIZED REPRESENTATIVE"):
                self.assertNotIn(label, pages[0])
                self.assertIn(label, pages[1])
            for value in bank.values():
                self.assertIn(value.encode(), pages[1])
            self.assertIn(b"/Im1 Do", pages[1])


if __name__ == "__main__":
    unittest.main()
