"""Private company directory; apply trusted defaults after source extraction."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


FIELDS = ('company_key', 'legal_name', 'aliases', 'address', 'contact', 'phone',
          'email', 'registration_details', 'default_ship_to', 'ship_to_phone')
TABLE = 'kekorea_counterparties'


def _name_key(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = re.sub(r'\b(?:co|company|pte|ltd|limited|inc|corporation|corp)\b', ' ', text)
    return ''.join(re.findall(r'[^\W_]+', text))


def _names(profile):
    return [profile.get('legal_name') or '', *profile.get('aliases', [])]


def _mentioned(prompt, profile):
    text = unicodedata.normalize('NFKC', str(prompt or '')).casefold()
    for name in _names(profile):
        key = _name_key(name)
        if key and re.search(r'(?<![a-z0-9])' + r'[\W_]*'.join(map(re.escape, key)) + r'(?![a-z0-9])', text):
            return True
    return False


def apply_company_profiles(draft, profiles, *, prompt=''):
    """Fill missing recipient fields; explicit order values always take priority."""
    dtype = draft.get('document_type')
    if dtype not in {'PI', 'PO', 'CI', 'PL'}:
        return draft
    role = 'seller' if dtype == 'PO' else 'buyer'
    party = draft.setdefault(role, {})
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
    # Supplier delivery defaults do not apply to a PO sent by KE KOREA.
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


def save_local_profile(path, profile):
    """Stage a durable private SQLite record, without embedding contacts in Git."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not profile.get('company_key') or not profile.get('legal_name'):
        raise ValueError('Company key and legal name are required')
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS counterparties (company_key TEXT PRIMARY KEY, profile_json TEXT NOT NULL)')
        db.execute('INSERT INTO counterparties VALUES (?, ?) ON CONFLICT(company_key) DO UPDATE SET profile_json=excluded.profile_json',
                   (profile['company_key'], json.dumps(profile, ensure_ascii=False)))


def load_local_profiles(path):
    if not Path(path).exists():
        return []
    with closing(sqlite3.connect(path)) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT profile_json FROM counterparties ORDER BY company_key')]


def _request(env, *, query=None, payload=None, opener=urlopen):
    base = str(env.get('SUPABASE_URL') or '').rstrip('/')
    key = str(env.get('SUPABASE_SECRET_KEY') or '')
    parsed = urlparse(base)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co')
            or parsed.path or parsed.query or parsed.fragment or not key):
        raise ValueError('Private company directory requires SUPABASE_URL and SUPABASE_SECRET_KEY')
    headers = {'apikey': key, 'Accept': 'application/json'}
    if key.startswith('eyJ'):
        headers['Authorization'] = 'Bearer ' + key
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers.update({'Content-Type': 'application/json',
                        'Prefer': 'resolution=merge-duplicates,return=representation'})
    url = base + '/rest/v1/' + TABLE + '?' + urlencode(query or {'select': ','.join(FIELDS)})
    request = Request(url, headers=headers, data=data, method='POST' if data is not None else 'GET')
    try:
        with opener(request, timeout=20) as response:
            result = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        raise RuntimeError(f'Company directory request failed (HTTP {exc.code}); check the private table and permissions') from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError('Company directory could not be reached') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('Company directory returned invalid data') from None
    if not isinstance(result, list):
        raise RuntimeError('Company directory returned an unexpected response')
    return result


def load_company_profiles(env, *, opener=urlopen):
    records = []
    for offset in range(0, 10000, 500):
        page = _request(env, query={'select': ','.join(FIELDS), 'order': 'company_key',
                                   'limit': 500, 'offset': offset}, opener=opener)
        for record in page:
            if (not isinstance(record, dict) or not record.get('company_key') or not record.get('legal_name')
                    or not isinstance(record.get('aliases'), list)):
                raise RuntimeError('Company directory contains an invalid record')
        records.extend(page)
        if len(page) < 500:
            return records
    raise RuntimeError('Company directory exceeds the supported record limit')


def upsert_company_profile(env, profile, *, opener=urlopen):
    """Update only this company, preserving previously known unspecified fields."""
    key = profile.get('company_key')
    if not key or not profile.get('legal_name'):
        raise ValueError('Company key and legal name are required')
    existing = _request(env, query={'select': ','.join(FIELDS), 'company_key': 'eq.' + key}, opener=opener)
    if len(existing) > 1:
        raise RuntimeError('Company directory key is not unique')
    merged = deepcopy(existing[0]) if existing else {}
    merged.update({k: v for k, v in profile.items() if k in FIELDS and v is not None})
    merged['aliases'] = sorted(set((existing[0].get('aliases', []) if existing else []) + profile.get('aliases', [])))
    merged['updated_at'] = datetime.now(timezone.utc).isoformat()
    result = _request(env, query={'on_conflict': 'company_key', 'select': ','.join(FIELDS)}, payload=merged, opener=opener)
    if len(result) != 1 or any(result[0].get(k) != v for k, v in merged.items() if k in FIELDS):
        raise RuntimeError('Company directory write could not be verified')
    return result[0]
