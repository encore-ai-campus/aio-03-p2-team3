"""A separate, unresolved promotion must not erase prices for matched PO rows."""
import copy
import unittest

from Quotation_KEKOREA.agent.pricing import apply_verified_eclado_prices


def partial_order():
    # Synthetic prices only; reproduce 24 matched image rows plus one ambiguous
    # promotion row, without embedding the private purchase-price workbook.
    products = [dict(id=f'p{i}', brand='ECLADO', item_name=f'Image product {i}',
                     capacity='100ml') for i in range(24)]
    products += [dict(id=f't{i}', brand='ECLADO', item_name='Melaser Whitening Toner',
                      capacity=capacity) for i, capacity in enumerate(('150ml', None))]
    catalog = dict(products=products, purchase_prices=[
        dict(product_id=p['id'], supplier_key='ECLADO', currency='KRW',
             unit_price='1000', source_row=i + 1) for i, p in enumerate(products)])
    draft = dict(document_type='PO', product_family='cosmetics', currency=None,
                 seller=dict(legal_name=None), items=[
                     dict(product_name=p['item_name'], capacity=p['capacity'],
                          quantity='10', unit_price=None) for p in products[:24]])
    draft['items'].append(dict(product_name='Melaser Whitening Toner', capacity=None,
                               quantity=None, unit_price=None, promotion='Buy 3, get 1 free'))
    return draft, catalog


class PartialPoCatalogTests(unittest.TestCase):
    def test_missing_supplier_and_ambiguous_promotion_keep_24_verified_prices(self):
        draft, catalog = partial_order()
        original_items = copy.deepcopy(draft['items'])
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['currency'], 'KRW')
        self.assertEqual([row.get('unit_price') for row in draft['items'][:24]], ['1000'] * 24)
        self.assertTrue(all(row['master_price'] for row in draft['items'][:24]))
        self.assertIsNone(draft['seller']['legal_name'])
        self.assertEqual(draft['pending_confirmations'], [])
        toner = draft['items'][-1]
        self.assertIsNone(toner['unit_price'])
        self.assertIsNone(toner['quantity'])
        self.assertFalse(toner['master_price'])
        self.assertTrue(any('Exact ECLADO product match for Melaser' in issue
                            for issue in draft['missing_fields']))
        self.assertEqual([(r['product_name'], r['capacity'], r['quantity']) for r in draft['items']],
                         [(r['product_name'], r['capacity'], r['quantity']) for r in original_items])
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['pending_confirmations'], [])

    def test_po_uses_eclado_purchase_prices_regardless_of_source_seller_or_currency(self):
        for supplier, currency in (('Other supplier', None), ('다른 공급처', None), (None, 'USD')):
            with self.subTest(supplier=supplier, currency=currency):
                draft, catalog = partial_order()
                draft['seller']['legal_name'] = supplier
                draft['currency'] = currency
                apply_verified_eclado_prices(draft, catalog)
                self.assertEqual(draft['currency'], 'KRW')
                self.assertEqual([row['unit_price'] for row in draft['items'][:24]], ['1000'] * 24)
                self.assertIsNone(draft['items'][-1]['unit_price'])

    def test_no_exact_matches_do_not_infer_price_but_po_currency_stays_krw(self):
        draft, catalog = partial_order()
        draft['product_family'] = 'other'
        draft['items'] = [dict(product_name='Unrelated product', capacity='10ml',
                               quantity='1', unit_price='5', source='USD 5 each')]
        apply_verified_eclado_prices(draft, catalog)
        self.assertEqual(draft['currency'], 'KRW')
        self.assertEqual(draft['pending_confirmations'], [])
        self.assertEqual(draft['product_family'], 'cosmetics')
        self.assertIsNone(draft['items'][0]['unit_price'])
        self.assertTrue(any('Exact ECLADO product match for Unrelated product' in issue
                            for issue in draft['missing_fields']))
