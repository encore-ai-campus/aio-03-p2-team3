"""거래처 프로필 적용(kekorea-port 2절 A가 추출 순서에 쓰고, 3절 B가 조회·저장을 더한다).

원본: reference/kekorea/Quotation_KEKOREA/agent/counterparties.py 중 적용 함수만 복사.
계약 15.4절: `load_company_profiles`·`save_local_profile`·`load_local_profiles`·
`upsert_company_profile`·Supabase 접근은 옮기지 않고, 3절(B)이 `counterparties` 표
(계약 15.7절) 조회·저장으로 대체한다. 프로필 dict의 키는 원본 FIELDS와 같다.
"""
import re
import unicodedata


FIELDS = ('company_key', 'legal_name', 'aliases', 'address', 'contact', 'phone',
          'email', 'registration_details', 'default_ship_to', 'ship_to_phone')


# 원본: reference/kekorea/Quotation_KEKOREA/agent/counterparties.py _name_key
def _name_key(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = re.sub(r'\b(?:co|company|pte|ltd|limited|inc|corporation|corp)\b', ' ', text)
    return ''.join(re.findall(r'[^\W_]+', text))


# 원본 _name_key 규칙을 그대로 노출한 공개 별칭(계약 15.4절: 발행사 키 `issuer_key`와
# 가격 행 `party_key` 비교에 kekorea-port 3절 B가 쓴다).
def name_key(value):
    return _name_key(value)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/counterparties.py _names
def _names(profile):
    return [profile.get('legal_name') or '', *profile.get('aliases', [])]


# 원본: reference/kekorea/Quotation_KEKOREA/agent/counterparties.py _mentioned
def _mentioned(prompt, profile):
    text = unicodedata.normalize('NFKC', str(prompt or '')).casefold()
    for name in _names(profile):
        key = _name_key(name)
        if key and re.search(r'(?<![a-z0-9])' + r'[\W_]*'.join(map(re.escape, key)) + r'(?![a-z0-9])', text):
            return True
    return False


# 원본: reference/kekorea/Quotation_KEKOREA/agent/counterparties.py apply_company_profiles
def apply_company_profiles(draft, profiles, *, prompt=''):
    """Fill missing recipient fields; explicit order values always take priority."""
    dtype = draft.get('document_type')
    if dtype not in {'PI', 'PO', 'CI', 'PL'}:
        return draft
    role = 'seller' if dtype == 'PO' else 'buyer'
    party = draft.get(role)
    if not isinstance(party, dict):
        # KNOWN_ERRORS ERR-13 대응: null/목록 당사자로 예외가 나지 않게 빈 값으로 다룬다(이식 규칙 5).
        party = {}
        draft[role] = party
    supplied_name = str(party.get('legal_name') or '').strip()
    previous = draft.get('_company_profile', {})
    if (not profiles and previous.get('role') == role and supplied_name
            and _name_key(supplied_name) == _name_key(previous.get('legal_name'))):
        # A directory outage cannot erase a reviewed document's saved identity.
        return draft
    if supplied_name:
        key = _name_key(supplied_name)
        matches = [p for p in profiles if key and key in {_name_key(n) for n in _names(p)}]
    else:
        matches = [p for p in profiles if _mentioned(prompt, p)]
    draft.pop('_company_profile', None)
    for path, original_value in previous.get('fields', {}).items():
        parts = path.split('.')
        target = draft.get(parts[0], {}) if len(parts) == 2 else draft
        field = parts[-1]
        if isinstance(target, dict) and target.get(field) == original_value:
            target[field] = previous.get('source_name') if path == role + '.legal_name' else None
    if len(matches) != 1:
        return draft
    profile = matches[0]
    applied = {}
    # The exact registered legal name replaces only a recognized name alias.
    party['legal_name'] = profile['legal_name']
    if supplied_name != profile['legal_name'] or role + '.legal_name' in previous.get('fields', {}):
        applied[role + '.legal_name'] = profile['legal_name']
    for field in ('address', 'contact', 'phone', 'email', 'registration_details'):
        value = profile.get(field)
        if party.get(field) in (None, '') and value not in (None, ''):
            party[field] = value
            applied[role + '.' + field] = value
    # A registered address is never inferred to be a delivery destination.
    # Supplier delivery defaults do not apply to a PO issued by our company.
    if dtype != 'PO' and draft.get('ship_to') in (None, '') and profile.get('default_ship_to'):
        destination = profile['default_ship_to']
        if profile.get('ship_to_phone') not in (None, ''):
            destination += ' / Tel: ' + profile['ship_to_phone']
        draft['ship_to'] = destination
        applied['ship_to'] = destination
    draft['_company_profile'] = {'company_key': profile['company_key'], 'role': role,
                                'legal_name': profile['legal_name'], 'fields': applied,
                                'source_name': (previous.get('source_name', supplied_name)
                                                if previous.get('company_key') == profile['company_key']
                                                and previous.get('role') == role else supplied_name)}
    return draft
