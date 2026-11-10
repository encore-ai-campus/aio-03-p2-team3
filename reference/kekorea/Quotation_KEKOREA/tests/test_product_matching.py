"""Decorated product names must match without guessing a different SKU or size."""
import copy
import unittest

from Quotation_KEKOREA.agent.pricing import (match_eclado_product, apply_catalog_product_matches,
    apply_verified_eclado_prices)


PRODUCTS = [
    dict(id='cream50', brand='ECLADO', kind='standard', source_code='E-165',
         item_name='Cell Memory Cream', capacity='50g'),
    dict(id='cream200', brand='ECLADO', kind='standard', source_code='E-166-1',
         item_name='Cell Memory Cream', capacity='200g'),
    dict(id='toner', brand='ECLADO', kind='standard', source_code='E173A',
         item_name='Respiration Toner', capacity='150ml'),
    dict(id='serum', brand='ECLADO', kind='standard', source_code='E-20',
         item_name='Shining V-C Serum', capacity='100ml'),
    dict(id='ampoule', brand='ECLADO', kind='standard', source_code='NK-CX',
         item_name='NK-CX Core Ampoule', capacity='5ml*6, 7ml*6'),
    dict(id='fiber', brand='ECLADO', kind='standard', source_code='F-1',
         item_name='Rejuven Fiber&Ampoule System', capacity='(1g + 10ml)*6'),
    dict(id='gold', brand='ECLADO', kind='standard', source_code='G-1',
         item_name='Vital Lift Pack Gold', capacity='3gx10,100ml'),
    dict(id='double', brand='ECLADO', kind='standard', source_code='D-1',
         item_name='NK-CX Core Cream', capacity='25g*2'),
]


class ProductMatchingTests(unittest.TestCase):
    def match(self, name, capacity='50g', products=PRODUCTS, **kwargs):
        return match_eclado_product(name, capacity, products, **kwargs)

    def test_code_brackets_labels_and_unicode_punctuation_preserve_identity(self):
        variants = [
            'Cell Memory Cream (E-165)', '[E165] Cell Memory Cream',
            'E-165 | Cell Memory Cream', 'Cell Memory Cream【E－165】',
            'ECLADO / Item: Cell Memory Cream / SKU: E-165',
            '제품명: Cell Memory Cream (제품코드: E165)',
            'Ｃｅｌｌ　Ｍｅｍｏｒｙ　Ｃｒｅａｍ（Ｅ－１６５）',
            'cell-memory-cream', 'Cell\nMemory\tCream', 'Cell\u200b Memory Cream',
            '“Cell Memory Cream”', 'CellMemoryCream',
            'Cell (Memory) Cream', 'Cell Memory Cream — Capacity: 50 grams',
            'Item No: E165 — Cell Memory Cream — Qty: 10 PCS',
            'Cell Memory Cream (SKU: E - 165)',
            'Cell [E165] Memory Cream', 'Cell (SKU: E165) Memory Cream',
        ]
        for name in variants:
            with self.subTest(name=name):
                result = self.match(name)
                self.assertEqual(result['status'], 'matched')
                self.assertEqual(result['product']['id'], 'cream50')

    def test_full_name_with_extra_description_gets_price_candidate_and_confirmation(self):
        draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                     seller={'legal_name': 'ECLADO'}, items=[dict(
                         product_name='Cell Memory Cream (for dry skin)', capacity='50g',
                         quantity='10', unit_price=None)])
        catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                       supplier_key='ECLADO', currency='KRW', unit_price='1000')])
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['items'][0]['unit_price'], '1000')
        self.assertTrue(any('Confirm product annotation' in c for c in draft['pending_confirmations']))
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(len(draft['pending_confirmations']), 1)
        draft['items'][0]['product_name'] = 'Cell Memory Cream'
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['pending_confirmations'], [])

    def test_capacity_units_multipliers_and_decimal_formatting(self):
        cases = [('Cell Memory Cream', '50.0 G', 'cream50'),
                 ('Respiration Toner', '150 millilitres', 'toner'),
                 ('NK-CX Core Ampoule (NK-CX)', '5 mL × 6, 7 mL X 6', 'ampoule'),
                 ('Rejuven Fiber and Ampoule System', '(1 g + 10 ml) × 6', 'fiber'),
                 ('Vital Lift Pack Gold (G-1)', '3 g * 10, 100 mL', 'gold'),
                 ('NK-CX Core Cream', '2 × 25 grams', 'double')]
        for name, capacity, expected in cases:
            with self.subTest(name=name, capacity=capacity):
                result = self.match(name, capacity)
                self.assertEqual(result['status'], 'matched')
                self.assertEqual(result['product']['id'], expected)

    def test_codes_and_inline_size_disambiguate_but_do_not_override_conflicts(self):
        self.assertEqual(self.match('Cell Memory Cream (E165)', None)['product']['id'], 'cream50')
        self.assertEqual(self.match('Cell Memory Cream [50g]', None)['product']['id'], 'cream50')
        self.assertEqual(self.match('Cell Memory Cream', None)['status'], 'ambiguous')
        bad = [('Cell Memory Cream (E-166-1)', '50g'),
               ('Cell Memory Cream [E999]', '50g'),
               ('Cell Memory Cream SKU: E-999', '50g'),
               ('Cell Memory Cream Item No: E-999', '50g'),
               ('Cell Memory Cream (200g)', '50g'),
               ('Cell [E-166-1] Memory Cream', '50g'),
               ('Cell Memory Cream (E-165) (E-166-1)', '50g'),
               ('Cell Memory Cream / Respiration Toner', '50g'),
               ('Not Cell Memory Cream', '50g'),
               ('Unrelated Toner (E-165)', '50g')]
        for name, capacity in bad:
            with self.subTest(name=name):
                self.assertNotEqual(self.match(name, capacity)['status'], 'matched')

    def test_sample_refill_and_formula_variants_are_not_silently_dropped(self):
        for word in ('Sample', 'Tester', 'Refill', 'Mini', 'Plus', '샘플', '리필', 'new formula'):
            with self.subTest(word=word):
                self.assertNotEqual(self.match('Cell Memory Cream (' + word + ')')['status'], 'matched')
        products = PRODUCTS + [dict(id='plus', brand='ECLADO', item_name='Cell Memory Cream Plus', capacity='50g')]
        self.assertEqual(self.match('Cell Memory Cream Plus', products=products)['product']['id'], 'plus')

    def test_wrong_compound_sizes_and_omitted_product_words_are_rejected(self):
        for name, size in [('Cell Memory Cream', '50ml'),
                           ('NK-CX Core Cream', '50g'),
                           ('NK-CX Core Cream', '25g*3'),
                           ('NK-CX Core Ampoule', '5ml*6'),
                           ('Rejuven Fiber&Ampoule System', '1g+10ml*6'),
                           ('Cell Cream', '50g'), ('Shining Serum', '100ml'),
                           ('SuperCell Memory Cream', '50g')]:
            with self.subTest(name=name, size=size):
                self.assertNotEqual(self.match(name, size)['status'], 'matched')

    def test_structured_code_must_agree_with_product_name_and_capacity(self):
        self.assertEqual(self.match('Cell Memory Cream', None, product_code='E165')['product']['id'], 'cream50')
        self.assertNotEqual(self.match('Cell Memory Cream', '50g', product_code='E166-1')['status'], 'matched')
        self.assertNotEqual(self.match('Respiration Toner', '150ml', product_code='E165')['status'], 'matched')

    def test_high_similarity_ocr_typo_resolves_catalog_candidate_but_requires_double_check(self):
        result = self.match('Cell Mem0ry Cream', '50g')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['match_method'], 'fuzzy')
        self.assertEqual(result['product']['id'], 'cream50')
        self.assertGreaterEqual(result['similarity'], 0.90)
        self.assertIn('Double-check this product', result['confirmation'])
        self.assertEqual(self.match('Cell Mem0ry Cream', '50g', product_code='E165')['product']['id'], 'cream50')
        self.assertEqual(self.match('Cell Mem0ry Cream', '50ml')['status'], 'not_found')
        self.assertEqual(self.match('Cell Mem0ry Cream', '50g', product_code='UNKNOWN')['status'], 'not_found')
        self.assertEqual(self.match('Cell Mem0ry Cream', '50g', product_code='E166-1')['status'], 'not_found')

    def test_lower_similarity_returns_review_suggestions_without_auto_match(self):
        result = self.match('Cell Memery Crim', '50g')
        self.assertEqual(result['status'], 'suggested')
        self.assertEqual(result['suggestions'][0]['product']['id'], 'cream50')
        self.assertLess(result['suggestions'][0]['similarity'], 0.90)

    def test_longer_sku_is_not_mistaken_for_its_prefix(self):
        products = PRODUCTS + [dict(id='collagen', brand='ECLADO', source_code='E-20-8',
                                    item_name='COLLAGEN 5000 SERUM', capacity='100ml')]
        for name in ('COLLAGEN 5000 SERUM SKU: E-20-8', 'E-20-8 | COLLAGEN 5000 SERUM',
                     'COLLAGEN 5000 SERUM (E-20-8)'):
            with self.subTest(name=name):
                self.assertEqual(self.match(name, '100ml', products)['product']['id'], 'collagen')
        self.assertNotEqual(self.match('COLLAGEN 5000 SERUM (E-20)', '100ml', products)['status'], 'matched')
        for name in ('Shining V-C Serum SKU: E-20-999', 'E-20-999 | Shining V-C Serum'):
            with self.subTest(name=name):
                self.assertNotEqual(self.match(name, '100ml', products)['status'], 'matched')

    def test_spf_and_pa_ratings_are_product_identity_not_disposable_punctuation(self):
        products = [dict(id='sun', brand='ECLADO', item_name='Natural Perfect Sun Cream SPF50+ PA+++', capacity='70g')]
        self.assertEqual(self.match('Natural Perfect Sun Cream SPF 50+ PA+++', '70g', products)['status'], 'matched')
        for name in ('Natural Perfect Sun Cream SPF50 PA+', 'Natural Perfect Sun Cream SPF50+ PA++',
                     'Natural Perfect Sun Cream SPF50+ PA++++'):
            with self.subTest(name=name):
                self.assertNotEqual(self.match(name, '70g', products)['status'], 'matched')

    def test_inline_compact_or_annotated_sizes_cannot_override_full_specification(self):
        for name, size in [('Cell Memory Cream 200gx2', '50g'),
                           ('Cell Memory Cream (50mg)', '50g'),
                           ('Cell Memory Cream (50毫升)', '50g'),
                           ('NK-CX Core Cream 25gx3', '25g*2'),
                           ('NK-CX Core Ampoule (5ml*6 for treatment)', '5ml*6, 7ml*6'),
                           ('Rejuven Fiber&Ampoule System ((1g+10ml)*3 for treatment)', '(1g+10ml)*6')]:
            with self.subTest(name=name):
                self.assertNotEqual(self.match(name, size)['status'], 'matched')

    def test_duplicate_catalog_and_normalized_name_collisions_remain_ambiguous(self):
        products = PRODUCTS + [{**PRODUCTS[0], 'id': 'duplicate'}]
        self.assertEqual(self.match('Cell Memory Cream (E165)', products=products)['status'], 'ambiguous')
        products = PRODUCTS + [dict(id='collision', brand='ECLADO', item_name='Cell-Memory Cream', capacity='50g')]
        self.assertEqual(self.match('CELL MEMORY CREAM', products=products)['status'], 'ambiguous')

    def test_matching_never_mutates_input_or_selects_other_brand(self):
        products = copy.deepcopy(PRODUCTS)
        before = copy.deepcopy(products)
        self.match('Cell Memory Cream (E165)', products=products)
        self.assertEqual(products, before)
        self.assertEqual(self.match('Cell Memory Cream', products=[{**PRODUCTS[0], 'brand': 'OTHER'}])['status'], 'not_found')

    def test_match_only_preserves_manual_names_and_document_prices(self):
        draft = dict(document_type='PL', items=[dict(
            product_name='Cell Memery Crim', capacity='50g', product_id='cream50',
            unit_price='42', price_basis='USD/PCS', price_source='Source document')])
        apply_catalog_product_matches(draft, {'products': PRODUCTS})
        item = draft['items'][0]
        self.assertEqual(item['product_name'], 'Cell Memery Crim')
        self.assertEqual(item['unit_price'], '42')
        self.assertEqual(item['price_basis'], 'USD/PCS')
        self.assertEqual(item['price_source'], 'Source document')
        self.assertNotIn('product_id', item)
        self.assertTrue(any(message.startswith('Double-check this product:')
                            for message in draft['pending_confirmations']))

        item['product_name'] = 'Manual product name'
        apply_catalog_product_matches(draft, {'products': PRODUCTS})
        self.assertEqual(item['product_name'], 'Manual product name')
        self.assertEqual(item['unit_price'], '42')

    def test_catalog_price_is_cleared_if_a_previously_matched_sku_becomes_conflicting(self):
        draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                     seller={'legal_name': 'ECLADO'}, items=[dict(
                         product_name='Cell Memory Cream', capacity='50g', quantity='10')])
        catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                       supplier_key='ECLADO', currency='KRW', unit_price='1000')])
        apply_verified_eclado_prices(draft, catalog)
        self.assertTrue(draft['items'][0]['master_price'])
        draft['items'][0]['product_name'] = 'Cell Memory Cream (E-166-1)'
        apply_verified_eclado_prices(draft, catalog)
        self.assertIsNone(draft['items'][0].get('unit_price'))
        self.assertIsNone(draft['items'][0].get('product_id'))

    def test_high_similarity_imports_price_but_keeps_source_name_and_requires_confirmation(self):
        draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                     seller={'legal_name': 'ECLADO'}, items=[dict(
                         product_name='Cell Mem0ry Cream', capacity='50g',
                         quantity='10', unit_price=None)])
        catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                       supplier_key='ECLADO', currency='KRW', unit_price='1000')])
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['items'][0]['unit_price'], '1000')
        self.assertEqual(draft['items'][0]['product_name'], 'Cell Mem0ry Cream')
        self.assertTrue(draft['items'][0]['master_price'])
        self.assertTrue(any(message.startswith('Double-check this product:')
                            for message in draft['pending_confirmations']))

    def test_lower_similarity_does_not_import_price_and_preserves_user_entered_name_and_price(self):
        draft = dict(document_type='PO', product_family='cosmetics', currency='KRW',
                     seller={'legal_name': 'ECLADO'}, items=[dict(
                         product_name='Cell Memery Crim', capacity='50g',
                         quantity='10', unit_price='42',
                         price_source='User-entered value in document review')])
        catalog = dict(products=PRODUCTS, purchase_prices=[dict(product_id='cream50',
                       supplier_key='ECLADO', currency='KRW', unit_price='1000')])
        apply_verified_eclado_prices(draft, catalog)
        self.assertIsNone(draft['items'][0].get('product_id'))
        self.assertFalse(draft['items'][0]['master_price'])
        self.assertEqual(draft['items'][0]['unit_price'], '42')
        self.assertTrue(any(message.startswith('Double-check this product:')
                            for message in draft['pending_confirmations']))
        draft['items'][0]['product_name'] = 'Customer-entered product name'
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['items'][0]['product_name'], 'Customer-entered product name')
        self.assertEqual(draft['items'][0]['unit_price'], '42')
