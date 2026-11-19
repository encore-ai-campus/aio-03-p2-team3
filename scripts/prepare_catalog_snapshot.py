"""Read-only catalog preparation on the owner's PC; no LLM calls or migrations.

Only DATABASE_URL is used from the existing environment/.env. The operator must
specify their own account email. This local extraction is not application login
or proof that the eventual server selection/ownership boundary has passed.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import ipaddress
import re
import os
from pathlib import Path
import tempfile
import zipfile

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url


class Unconfirmed(Exception):
    pass


def database_url(repo):
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        # Do not expand other environment values or load them into the process.
        url = str(dotenv_values(repo / '.env', interpolate=False).get('DATABASE_URL') or '').strip()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if not url.startswith('postgresql+psycopg://'):
        raise Unconfirmed('database_configuration_unconfirmed')
    return url


def public_connection_hint(url):
    """Return coarse labels only, never actual host/user/password/database values."""
    parsed = make_url(url)
    host = (parsed.host or '').lower()
    provider = 'unidentified'
    if host.endswith('.pooler.supabase.com'):
        provider = 'supabase_pooler'
    elif host.startswith('db.') and host.endswith('.supabase.co'):
        provider = 'supabase_direct'
    elif host.endswith('.render.com') or host.startswith('dpg-'):
        provider = 'render_postgres'
    scope = 'public_hostname_or_address'
    if not host:
        scope = 'host_missing'
    elif host == 'localhost':
        scope = 'local_host'
    elif '.' not in host and ':' not in host or host.endswith('.internal'):
        scope = 'private_or_internal_hostname'
    else:
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback:
                scope = 'local_host'
            elif address.is_private:
                scope = 'private_ip_address'
        except ValueError:
            pass
    return {'provider_hint': provider, 'host_scope_hint': scope,
            'port': parsed.port or 5432,
            'username_present': bool(parsed.username),
            'password_present': bool(parsed.password),
            'database_name_present': bool(parsed.database)}


def safe_database_error(error):
    """Inspect raw driver errors privately and emit only fixed cause codes."""
    original = getattr(error, 'orig', error)
    state = getattr(original, 'sqlstate', None)
    if not isinstance(state, str) or not re.fullmatch(r'[0-9A-Z]{5}', state):
        state = None
    codes = {'28P01': 'authentication_failed', '28000': 'authentication_failed',
             '3D000': 'database_not_found', '42P01': 'required_table_missing',
             '42703': 'required_column_missing', '42501': 'database_permission_denied',
             '53300': 'database_connection_limit', '57P03': 'database_temporarily_unavailable',
             '57014': 'database_query_timeout', '25006': 'readonly_transaction_rejected_write'}
    cause = codes.get(state)
    if cause is None:
        message = str(original).casefold()  # Never returned, printed or written.
        patterns = [
            ('dns_resolution_failed', ('could not translate host name', 'name or service not known',
                                      'getaddrinfo failed', 'nodename nor servname',
                                      'no such host is known', 'failed to resolve host')),
            ('authentication_failed', ('password authentication failed', 'authentication failed')),
            ('network_unreachable', ('network is unreachable', 'no route to host')),
            ('connection_refused', ('connection refused', 'actively refused')),
            ('connection_timeout', ('connection timeout', 'connection timed out', 'timeout expired')),
            ('tls_configuration_failed', ('certificate verify failed', 'ssl connection is required',
                                          'ssl is not enabled', 'server does not support ssl',
                                          'tls handshake', 'ssl handshake')),
            ('database_user_or_pooler_not_found', ('tenant or user not found',)),
        ]
        cause = next((code for code, phrases in patterns if any(p in message for p in phrases)),
                     'database_error_unclassified')
    result = {'cause_code': cause}
    if state:
        result['sqlstate'] = state
    return result


def connection_options(url, timeout, require_tls):
    options = {'connect_timeout': timeout}
    if require_tls:
        mode = make_url(url).query.get('sslmode')
        options['sslmode'] = mode if mode in {'verify-ca', 'verify-full'} else 'require'
    return options


def read_owned_catalog(connection, owner_email, role):
    if not owner_email or role not in {'sale', 'purchase'}:
        raise Unconfirmed('owner_or_role_unconfirmed')
    # First statements of this transaction. No application bootstrap/migrations.
    connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
    connection.execute(text("SET LOCAL statement_timeout = '5s'"))
    owners = connection.execute(text(
        'SELECT id FROM users WHERE lower(email) = :email LIMIT 2'),
        {'email': owner_email.strip().lower()}).scalars().all()
    if len(owners) != 1:
        raise Unconfirmed('owner_not_found_or_ambiguous')
    rows = connection.execute(text('''
        SELECT id, item_name, product_code, capacity, unit, role
        FROM price_list_items
        WHERE user_id = :owner AND role = :role ORDER BY id LIMIT 201
    '''), {'owner': owners[0], 'role': role}).mappings().all()
    if not rows:
        raise Unconfirmed('owned_catalog_empty')
    if len(rows) > 200:
        raise Unconfirmed('catalog_over_200_requires_recall_plan')
    # Real database IDs are serialized as strings for the existing benchmark.
    products = [{'id': str(row['id']), 'item_name': row['item_name'],
                 'source_code': row['product_code'], 'capacity': row['capacity'],
                 'unit': row['unit'], 'role': row['role']} for row in rows]
    version = sha256(json.dumps(products, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
    return {'document_type': 'owned_catalog_benchmark_snapshot',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'products': products, 'catalog_snapshot_sha256': version, 'role': role,
            'selection_method': 'operator_supplied_email_exact_unique_db_match',
            'database_transaction_read_only': True, 'api_calls': 0,
            'queries': [], 'query_ground_truth': 'unconfirmed',
            'application_authenticated_owner_verified': False,
            'server_id_owner_version_revalidation_verified': False}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--role', choices=['sale', 'purchase'], default='sale')
    parser.add_argument('--change-owner', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--connect-timeout', type=int, choices=range(1, 61), default=5)
    parser.add_argument('--require-tls', action='store_true')
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / 'app/evaluation/model_benchmark.py').is_file():
        parser.error('Existing PC repository required. No files modified.')
    parent = repo.parent / (repo.name + '-catalog-preparation')
    parent.mkdir(parents=True, exist_ok=True)
    state_path = parent / 'private-state.json'
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if args.change_owner:
        state.pop('owner_email', None)
        state.pop('sale_completed_archive', None)
        state.pop('purchase_completed_archive', None)
    archive_key = args.role + '_completed_archive'
    if not args.refresh and not args.change_owner and state.get(archive_key):
        archive = Path(state[archive_key])
        if archive.is_file():
            print('Existing snapshot preserved; attach:', archive)
            print('Use --refresh only to explicitly collect a newer snapshot.')
            return 0
    out = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=parent))
    status = {'status': 'unconfirmed', 'api_calls': 0, 'database_writes': 0,
              'role': args.role, 'overall_model_setting_approved': False,
              'tool_version': 'catalog-snapshot-v3', 'failed_stage': 'configuration',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'connect_timeout_seconds': args.connect_timeout,
              'tls_required': args.require_tls}
    snapshot = None
    try:
        # Check configuration before asking the user for their account.
        url = database_url(repo)
        status['connection_hint'] = public_connection_hint(url)
        status['failed_stage'] = 'owner_selection'
        owner = state.get('owner_email')
        if not owner:
            owner = input('본인 앱 로그인 이메일 (모름/Enter/취소는 미확인): ').strip()
            if not owner or owner.casefold() in {'모름', '취소', 'unknown', 'cancel'}:
                raise Unconfirmed('owner_unconfirmed')
            if '@' not in owner or len(owner) > 320:
                raise Unconfirmed('owner_email_unconfirmed')
            state['owner_email'] = owner
            save(state_path, state)  # PC-private only; never included in the share ZIP.
        status['failed_stage'] = 'database_connect'
        engine = create_engine(url, echo=False, hide_parameters=True,
                               connect_args=connection_options(url, args.connect_timeout, args.require_tls),
                               poolclass=NullPool)
        try:
            with engine.connect() as connection:
                status['failed_stage'] = 'readonly_catalog_query'
                try:
                    snapshot = read_owned_catalog(connection, owner, args.role)
                finally:
                    connection.rollback()
        finally:
            engine.dispose()
        status.update(status='snapshot_collected_queries_unconfirmed',
                      product_count=len(snapshot['products']),
                      catalog_snapshot_sha256=snapshot['catalog_snapshot_sha256'], failed_stage=None)
    except Unconfirmed as error:
        snapshot = None
        status['reason_code'] = str(error)
    except (KeyboardInterrupt, EOFError):
        snapshot = None
        status['reason_code'] = 'cancelled_unconfirmed'
    except Exception as error:
        snapshot = None
        status['diagnostic'] = safe_database_error(error)
        # Never publish database URLs, SQL parameters, emails, keys or exception text.
        status.update(reason_code='database_or_local_configuration_unconfirmed',
                      error_type=type(error).__name__)
    save(out / 'collection-status.json', status)
    archive = out / 'catalog-snapshot.zip'
    if snapshot is not None:
        save(out / 'catalog-snapshot.json', snapshot)
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        z.write(out / 'collection-status.json', 'collection-status.json')
        if snapshot is not None:
            z.write(out / 'catalog-snapshot.json', 'catalog-snapshot.json')
    state['last_status'] = status
    if snapshot is not None:
        state[archive_key] = str(archive)
    save(state_path, state)
    print('상태:', status['status'], status.get('reason_code', ''))
    if status.get('diagnostic'):
        print('실패 단계/원인:', status['failed_stage'], status['diagnostic']['cause_code'])
    print('첨부할 파일:', archive)
    print('API 호출/과금/DB 쓰기/소스 변경 없음. 이메일·DB 주소·단가·키는 첨부에 포함하지 않습니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
