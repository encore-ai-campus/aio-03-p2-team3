"""거래처 프로필 적용 pytest(원본 tests/test_counterparties.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_counterparties.py
- SQLite 저장 시험(test_sqlite_save_is_durable...)은 저장소를 DB 표로 바꿔
  tests/test_trade_store.py의 조회 시험으로 옮겼다(계약 15.4절·15.7절).
- 발행사·거래처 이름은 가상 값으로 바꿨다. KNOWN_ERRORS ERR-13(null 당사자) 가드 시험을 더했다.
"""
import copy

from app.trade.common.counterparties import apply_company_profiles, name_key


PROFILE = dict(company_key='ACME_BUYER', legal_name='ACME BUYER PTE LTD',
               aliases=['Acme Buyer', 'AcmeBuyer'], address='Test Registered Address',
               contact='MS. TEST CONTACT', default_ship_to='Test Delivery Address',
               ship_to_phone='N/A')

ISSUER = 'Testworks Trading Co'


def test_alias_command_fills_pi_ci_and_packing_buyer_and_explicit_saved_delivery():
    for dtype in ('PI', 'CI', 'PL'):
        for alias in ('acme buyer', 'AcmeBuyer', 'ACME BUYER PTE LTD', 'Ａｃｍｅ　Ｂｕｙｅｒ'):
            draft = dict(document_type=dtype, buyer={}, seller={'legal_name': ISSUER})
            apply_company_profiles(draft, [PROFILE], prompt=alias + '에 인보이스 작성')
            assert draft['buyer']['legal_name'] == PROFILE['legal_name']
            assert draft['buyer']['address'] == 'Test Registered Address'
            assert draft['buyer']['contact'] == 'MS. TEST CONTACT'
            assert draft['ship_to'] == 'Test Delivery Address / Tel: N/A'
            assert draft['buyer'].get('phone') is None
            assert draft['buyer'].get('email') is None
            assert draft['seller']['legal_name'] == ISSUER


def test_explicit_order_values_and_na_take_priority():
    draft = dict(document_type='PI', buyer=dict(legal_name='acme buyer', address='Order Address',
                 contact='Order Contact', phone='N/A'), ship_to='Order Delivery')
    apply_company_profiles(draft, [PROFILE])
    assert draft['buyer']['address'] == 'Order Address'
    assert draft['buyer']['contact'] == 'Order Contact'
    assert draft['buyer']['phone'] == 'N/A'
    assert draft['ship_to'] == 'Order Delivery'


def test_po_fills_supplier_identity_without_using_supplier_delivery_as_ship_to():
    draft = dict(document_type='PO', buyer={'legal_name': ISSUER}, seller={'legal_name': 'Acme Buyer'})
    apply_company_profiles(draft, [PROFILE])
    assert draft['seller']['address'] == 'Test Registered Address'
    assert draft['buyer']['legal_name'] == ISSUER
    assert draft.get('ship_to') is None


def test_unknown_ambiguous_or_other_explicit_party_never_receives_profile():
    for name, prompt in (('Different Buyer', 'Acme Buyer invoice'), (None, 'NotAcmeBuyer invoice'),
                         (None, 'Please prepare an invoice')):
        draft = dict(document_type='PI', buyer={'legal_name': name})
        apply_company_profiles(draft, [PROFILE], prompt=prompt)
        assert draft['buyer'].get('address') is None
    draft = dict(document_type='PI', buyer={'legal_name': 'Acme Buyer'})
    apply_company_profiles(draft, [PROFILE, {**PROFILE, 'company_key': 'OTHER'}])
    assert draft['buyer'].get('address') is None


def test_switching_party_removes_only_previous_database_owned_fields():
    draft = dict(document_type='PI', buyer={'legal_name': 'Acme Buyer'})
    apply_company_profiles(draft, [PROFILE])
    draft['buyer']['legal_name'] = 'Different Buyer'
    draft['buyer']['contact'] = 'User edited contact'
    apply_company_profiles(draft, [PROFILE])
    assert draft['buyer'].get('address') is None
    assert draft['buyer']['contact'] == 'User edited contact'
    assert draft.get('ship_to') is None


def test_stored_address_alone_is_never_a_delivery_destination():
    profile = {**PROFILE, 'default_ship_to': None}
    draft = dict(document_type='PI', buyer={'legal_name': 'Acme Buyer'})
    apply_company_profiles(draft, [profile])
    assert draft.get('ship_to') is None


def test_saved_order_identity_survives_directory_unavailability():
    for name in ('Acme Buyer', PROFILE['legal_name']):
        draft = dict(document_type='PI', buyer={'legal_name': name})
        apply_company_profiles(draft, [PROFILE])
        before = copy.deepcopy(draft)
        apply_company_profiles(draft, [])
        assert draft == before
        draft['buyer']['legal_name'] = 'Different Buyer'
        apply_company_profiles(draft, [])
        assert draft['buyer']['legal_name'] == 'Different Buyer'
        assert draft['buyer'].get('address') is None


def test_exact_user_supplied_legal_name_survives_directory_record_removal():
    draft = dict(document_type='PI', buyer={'legal_name': PROFILE['legal_name']})
    apply_company_profiles(draft, [PROFILE])
    apply_company_profiles(draft, [{**PROFILE, 'company_key': 'SECOND', 'legal_name': 'Different Company', 'aliases': []}])
    assert draft['buyer']['legal_name'] == PROFILE['legal_name']


def test_switching_registered_companies_does_not_reuse_previous_name_provenance():
    second = {**PROFILE, 'company_key': 'SECOND', 'legal_name': 'SECOND LTD', 'aliases': ['Second']}
    draft = dict(document_type='PI', buyer={'legal_name': 'Acme Buyer'})
    apply_company_profiles(draft, [PROFILE, second])
    draft['buyer']['legal_name'] = 'Second'
    apply_company_profiles(draft, [PROFILE, second])
    apply_company_profiles(draft, [PROFILE])
    assert draft['buyer']['legal_name'] == 'Second'


def test_name_key_strips_legal_suffixes_and_punctuation():
    assert name_key('ACME BUYER PTE LTD') == name_key('acme buyer')
    assert name_key('Acme-Buyer Co., Ltd.') == 'acmebuyer'
    assert name_key('') == ''
    assert name_key(None) == ''


def test_null_or_malformed_party_does_not_crash_instead_of_err13():
    """KNOWN_ERRORS ERR-13: Advanced JSON의 null/목록 당사자가 예외를 일으키지 않게 한다."""
    for bad in (None, [], 'buyer'):
        draft = dict(document_type='PI', buyer=bad)
        apply_company_profiles(draft, [PROFILE], prompt='Acme Buyer 인보이스 작성')
        assert isinstance(draft['buyer'], dict)
        assert draft['buyer']['legal_name'] == PROFILE['legal_name']
        assert draft['buyer']['address'] == 'Test Registered Address'
