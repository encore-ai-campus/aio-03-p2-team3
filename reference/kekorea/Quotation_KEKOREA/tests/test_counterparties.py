"""Company records fill missing fields without mixing parties or destinations."""
import copy
from pathlib import Path
import tempfile
import unittest

from Quotation_KEKOREA.agent.counterparties import (
    apply_company_profiles, save_local_profile, load_local_profiles)


PROFILE = dict(company_key='DEAR_GLOW', legal_name='DEAR GLOW PTE LTD',
               aliases=['Dear Glow', 'Dearglow'], address='Test Registered Address',
               contact='MS. TEST CONTACT', default_ship_to='Test Delivery Address',
               ship_to_phone='N/A')


class CounterpartyTests(unittest.TestCase):
    def test_alias_command_fills_pi_ci_and_packing_buyer_and_explicit_saved_delivery(self):
        for dtype in ('PI', 'CI', 'PL'):
            for alias in ('dear glow', 'Dearglow', 'DEAR GLOW PTE LTD', 'Ｄｅａｒ Ｇｌｏｗ'):
                with self.subTest(dtype=dtype, alias=alias):
                    draft = dict(document_type=dtype, buyer={}, seller={'legal_name': 'KE KOREA'})
                    apply_company_profiles(draft, [PROFILE], prompt=alias + '에 인보이스 작성')
                    self.assertEqual(draft['buyer']['legal_name'], PROFILE['legal_name'])
                    self.assertEqual(draft['buyer']['address'], 'Test Registered Address')
                    self.assertEqual(draft['buyer']['contact'], 'MS. TEST CONTACT')
                    self.assertEqual(draft['ship_to'], 'Test Delivery Address / Tel: N/A')
                    self.assertIsNone(draft['buyer'].get('phone'))
                    self.assertIsNone(draft['buyer'].get('email'))
                    self.assertEqual(draft['seller']['legal_name'], 'KE KOREA')

    def test_explicit_order_values_and_na_take_priority(self):
        draft = dict(document_type='PI', buyer=dict(legal_name='dear glow', address='Order Address',
                     contact='Order Contact', phone='N/A'), ship_to='Order Delivery')
        apply_company_profiles(draft, [PROFILE])
        self.assertEqual(draft['buyer']['address'], 'Order Address')
        self.assertEqual(draft['buyer']['contact'], 'Order Contact')
        self.assertEqual(draft['buyer']['phone'], 'N/A')
        self.assertEqual(draft['ship_to'], 'Order Delivery')

    def test_po_fills_supplier_identity_without_using_supplier_delivery_as_ship_to(self):
        draft = dict(document_type='PO', buyer={'legal_name': 'KE KOREA'}, seller={'legal_name': 'Dear Glow'})
        apply_company_profiles(draft, [PROFILE])
        self.assertEqual(draft['seller']['address'], 'Test Registered Address')
        self.assertEqual(draft['buyer']['legal_name'], 'KE KOREA')
        self.assertIsNone(draft.get('ship_to'))

    def test_unknown_ambiguous_or_other_explicit_party_never_receives_profile(self):
        for name, prompt in (('Different Buyer', 'Dear Glow invoice'), (None, 'NotDearGlow invoice'),
                             (None, 'Please prepare an invoice')):
            with self.subTest(name=name, prompt=prompt):
                draft = dict(document_type='PI', buyer={'legal_name': name})
                apply_company_profiles(draft, [PROFILE], prompt=prompt)
                self.assertIsNone(draft['buyer'].get('address'))
        draft = dict(document_type='PI', buyer={'legal_name': 'Dear Glow'})
        apply_company_profiles(draft, [PROFILE, {**PROFILE, 'company_key': 'OTHER'}])
        self.assertIsNone(draft['buyer'].get('address'))

    def test_switching_party_removes_only_previous_database_owned_fields(self):
        draft = dict(document_type='PI', buyer={'legal_name': 'Dear Glow'})
        apply_company_profiles(draft, [PROFILE])
        draft['buyer']['legal_name'] = 'Different Buyer'
        draft['buyer']['contact'] = 'User edited contact'
        apply_company_profiles(draft, [PROFILE])
        self.assertIsNone(draft['buyer'].get('address'))
        self.assertEqual(draft['buyer']['contact'], 'User edited contact')
        self.assertIsNone(draft.get('ship_to'))

    def test_stored_address_alone_is_never_a_delivery_destination(self):
        profile = {**PROFILE, 'default_ship_to': None}
        draft = dict(document_type='PI', buyer={'legal_name': 'Dear Glow'})
        apply_company_profiles(draft, [profile])
        self.assertIsNone(draft.get('ship_to'))

    def test_saved_order_identity_survives_directory_unavailability(self):
        for name in ('Dear Glow', PROFILE['legal_name']):
            with self.subTest(name=name):
                draft = dict(document_type='PI', buyer={'legal_name': name})
                apply_company_profiles(draft, [PROFILE])
                before = copy.deepcopy(draft)
                apply_company_profiles(draft, [])
                self.assertEqual(draft, before)
                draft['buyer']['legal_name'] = 'Different Buyer'
                apply_company_profiles(draft, [])
                self.assertEqual(draft['buyer']['legal_name'], 'Different Buyer')
                self.assertIsNone(draft['buyer'].get('address'))

    def test_exact_user_supplied_legal_name_survives_directory_record_removal(self):
        draft = dict(document_type='PI', buyer={'legal_name': PROFILE['legal_name']})
        apply_company_profiles(draft, [PROFILE])
        apply_company_profiles(draft, [{**PROFILE, 'company_key': 'SECOND', 'legal_name': 'Different Company', 'aliases': []}])
        self.assertEqual(draft['buyer']['legal_name'], PROFILE['legal_name'])

    def test_switching_registered_companies_does_not_reuse_previous_name_provenance(self):
        second = {**PROFILE, 'company_key': 'SECOND', 'legal_name': 'SECOND LTD', 'aliases': ['Second']}
        draft = dict(document_type='PI', buyer={'legal_name': 'Dear Glow'})
        apply_company_profiles(draft, [PROFILE, second])
        draft['buyer']['legal_name'] = 'Second'
        apply_company_profiles(draft, [PROFILE, second])
        apply_company_profiles(draft, [PROFILE])
        self.assertEqual(draft['buyer']['legal_name'], 'Second')

    def test_sqlite_save_is_durable_and_updates_only_requested_company(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companies.sqlite3'
            save_local_profile(path, PROFILE)
            save_local_profile(path, {**PROFILE, 'company_key': 'SECOND', 'legal_name': 'Second Company'})
            changed = {**PROFILE, 'contact': 'Updated Contact'}
            before = copy.deepcopy(changed)
            save_local_profile(path, changed)
            self.assertEqual(changed, before)
            records = {p['company_key']: p for p in load_local_profiles(path)}
            self.assertEqual(records['DEAR_GLOW']['contact'], 'Updated Contact')
            self.assertEqual(records['SECOND']['legal_name'], 'Second Company')
