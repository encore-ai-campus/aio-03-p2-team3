"""Packing sum corrections require approval and preserve source evidence."""
import copy
import unittest

from Quotation_KEKOREA.agent.packing_review import (
    normalize_packing_inputs, packing_total_changes, apply_approved_packing_totals, reconcile_packing,
)
from Quotation_KEKOREA.tests.test_packing_workflow import packing_example


class PackingApprovalTests(unittest.TestCase):
    def test_explicit_units_and_container_size_are_parsed_without_multiplying(self):
        source = packing_example()
        source['container_count'] = '5 x 40FT Containers'
        source['declared_total_quantity'] = '618400 pcs'
        source['declared_net_weight_kg'] = '10,354.56 kg'
        result = normalize_packing_inputs(source)
        self.assertEqual(result['container_count'], '5')
        self.assertEqual(result['declared_total_quantity'], '618400')
        self.assertEqual(result['declared_total_quantity_unit'], 'PCS')
        self.assertEqual(result['declared_net_weight_kg'], '10354.56')
        self.assertEqual(result['_packing_original_totals']['container_count'], '5 x 40FT Containers')
        self.assertEqual(source['declared_total_quantity'], '618400 pcs')
        self.assertEqual(reconcile_packing(result)['issues'], [])

    def test_total_proposal_shows_mixed_units_and_preserves_source_until_approval(self):
        source = packing_example()
        original = copy.deepcopy(source)
        proposals = packing_total_changes(source)
        quantity = next(change for change in proposals if change['field'] == 'declared_total_quantity')
        self.assertIn('616001 PCS', quantity['calculated'])
        self.assertIn('2399.48 KG', quantity['calculated'])
        self.assertEqual(source, original)
        approved = apply_approved_packing_totals(source)
        self.assertEqual(approved['declared_volume_cbm'], '35.477')
        self.assertEqual(approved['declared_total_quantity'], '616001')
        self.assertEqual(approved['declared_total_quantity_unit'], 'PCS')
        self.assertEqual(approved['_packing_approved_quantities'], {'PCS': '616001', 'KG': '2399.48'})
        self.assertEqual(approved['_packing_original_totals']['declared_total_quantity'], '618400')
        self.assertEqual(approved['items'], source['items'])
        self.assertEqual(reconcile_packing(approved)['discrepancies'], [])
        self.assertEqual(source, original)

    def test_totals_approval_cannot_override_invalid_rows_or_container_counts(self):
        for field, value in (('gross_weight_kg', 'invalid'), ('gross_weight_kg', '1')):
            source = packing_example()
            source['items'][0][field] = value
            with self.assertRaises(ValueError):
                apply_approved_packing_totals(source)
        source = packing_example()
        source['container_count'] = 'five containers'
        with self.assertRaises(ValueError):
            apply_approved_packing_totals(source)

    def test_quantity_unit_conflicts_are_not_silently_reinterpreted(self):
        source = packing_example()
        source['declared_total_quantity'] = '618400 kg'
        source['declared_total_quantity_unit'] = 'PCS'
        normalized = normalize_packing_inputs(source)
        self.assertTrue(reconcile_packing(normalized)['issues'])
        with self.assertRaises(ValueError):
            apply_approved_packing_totals(normalized)
