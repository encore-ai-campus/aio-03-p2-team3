"""실제 임시 PostgreSQL로 개인 PC 카탈로그 준비의 읽기 경계를 검사한다."""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

spec = importlib.util.spec_from_file_location('catalog_snapshot', Path(__file__).parents[1] / 'scripts/prepare_catalog_snapshot.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


@pytest.fixture
def catalog_engine(database_url):
    engine = create_engine(database_url.replace('postgresql://', 'postgresql+psycopg://', 1))
    with engine.begin() as connection:
        # 테스트 DB는 앱 스키마가 이미 만들어진 세션 템플릿의 복제본이다(#282). 이 시험은 읽기 경계만 보는
        # 최소 표를 쓰므로, 이 테스트 전용 DB 안의 같은 이름 표를 먼저 지운다.
        connection.execute(text('DROP TABLE IF EXISTS price_list_items, users CASCADE'))
        connection.execute(text('CREATE TABLE users (id int PRIMARY KEY, email text)'))
        connection.execute(text('''CREATE TABLE price_list_items (
            id int PRIMARY KEY, user_id int, item_name text, product_code text,
            capacity text, unit text, role text, unit_price_text text)'''))
        connection.execute(text("INSERT INTO users VALUES (1,'owner@example.invalid'), (2,'other@example.invalid')"))
        connection.execute(text("""INSERT INTO price_list_items VALUES
            (11,1,'Owned Mouse','MOUSE','Black','PCS','sale','PRIVATE-PRICE'),
            (12,1,'Owned Purchase','PURCHASE',NULL,'PCS','purchase','OTHER-PRIVATE-PRICE'),
            (21,2,'Other User Product','SECRET',NULL,'PCS','sale','HIDDEN-PRICE')"""))
    yield engine
    engine.dispose()


def test_real_ids_owner_role_and_price_exclusion(catalog_engine):
    with catalog_engine.connect() as connection:
        result = snapshot.read_owned_catalog(connection, 'OWNER@EXAMPLE.INVALID', 'sale')
        assert connection.scalar(text('SHOW transaction_read_only')) == 'on'
        assert connection.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
        connection.rollback()
    assert [p['id'] for p in result['products']] == ['11']
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in ['PRIVATE-PRICE', 'Other User Product', 'owner@example'])
    assert result['application_authenticated_owner_verified'] is False
    assert result['queries'] == []


def test_snapshot_version_changes_for_catalog_change(catalog_engine):
    with catalog_engine.connect() as connection:
        original = snapshot.read_owned_catalog(connection, 'owner@example.invalid', 'sale')
        connection.rollback()
    with catalog_engine.begin() as connection:
        connection.execute(text("UPDATE price_list_items SET capacity='White' WHERE id=11"))
    with catalog_engine.connect() as connection:
        changed = snapshot.read_owned_catalog(connection, 'owner@example.invalid', 'sale')
        connection.rollback()
    assert original['catalog_snapshot_sha256'] != changed['catalog_snapshot_sha256']


def test_missing_or_ambiguous_owner_does_not_choose_another_user(catalog_engine):
    with catalog_engine.connect() as connection:
        with pytest.raises(snapshot.Unconfirmed, match='owner_not_found_or_ambiguous'):
            snapshot.read_owned_catalog(connection, 'missing@example.invalid', 'sale')
        connection.rollback()
    with catalog_engine.begin() as connection:
        connection.execute(text("INSERT INTO users VALUES (3,'OWNER@example.invalid')"))
    with catalog_engine.connect() as connection:
        with pytest.raises(snapshot.Unconfirmed, match='owner_not_found_or_ambiguous'):
            snapshot.read_owned_catalog(connection, 'owner@example.invalid', 'sale')
        connection.rollback()


def test_existing_database_config_does_not_load_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    (tmp_path / '.env').write_text('DATABASE_URL=postgresql://db.example.invalid/test\nOPENAI_API_KEY=DO-NOT-LOAD\n')
    assert snapshot.database_url(tmp_path) == 'postgresql+psycopg://db.example.invalid/test'
    import os
    assert 'OPENAI_API_KEY' not in os.environ


class CatalogConnection:
    def __init__(self, owners=(1,), rows=None):
        self.owners = list(owners)
        self.rows = rows if rows is not None else [{'id': 11, 'item_name': 'Owned Mouse',
            'product_code': 'MOUSE', 'capacity': 'Black', 'unit': 'PCS', 'role': 'sale'}]
        self.statements = []

    def execute(self, statement, parameters=None):
        from types import SimpleNamespace
        sql = str(statement)
        self.statements.append((sql, parameters))
        values = self.owners if 'FROM users' in sql else self.rows
        result = SimpleNamespace(all=lambda: values)
        return SimpleNamespace(scalars=lambda: result, mappings=lambda: result)


def test_readonly_and_owner_parameters_are_applied_before_catalog_read():
    connection = CatalogConnection()
    result = snapshot.read_owned_catalog(connection, 'Owner@Example.Invalid', 'sale')
    assert 'READ ONLY' in connection.statements[0][0]
    assert 'statement_timeout' in connection.statements[1][0]
    assert connection.statements[2][1] == {'email': 'owner@example.invalid'}
    assert connection.statements[3][1] == {'owner': 1, 'role': 'sale'}
    assert 'unit_price' not in connection.statements[3][0]
    assert result['products'][0]['id'] == '11'
    assert 'owner@example.invalid' not in json.dumps(result)


@pytest.mark.parametrize('owners', [[], [1, 2]])
def test_unconfirmed_owner_never_reads_catalog(owners):
    connection = CatalogConnection(owners=owners)
    with pytest.raises(snapshot.Unconfirmed, match='owner_not_found_or_ambiguous'):
        snapshot.read_owned_catalog(connection, 'owner@example.invalid', 'sale')
    assert not any('FROM price_list_items' in sql for sql, _ in connection.statements)


def test_over_limit_catalog_is_not_silently_truncated():
    connection = CatalogConnection(rows=CatalogConnection().rows * 201)
    with pytest.raises(snapshot.Unconfirmed, match='catalog_over_200'):
        snapshot.read_owned_catalog(connection, 'owner@example.invalid', 'sale')


@pytest.mark.parametrize('message,state,expected', [
    ('could not translate host name PRIVATE-DB-URL', None, 'dns_resolution_failed'),
    ('password authentication failed PRIVATE-PASSWORD', None, 'authentication_failed'),
    ('network is unreachable PRIVATE-HOST', None, 'network_unreachable'),
    ('connection timeout expired PRIVATE-HOST', None, 'connection_timeout'),
    ('certificate verify failed PRIVATE-CERT', None, 'tls_configuration_failed'),
    ('PRIVATE-USER PRIVATE-DB', '28P01', 'authentication_failed'),
    ('PRIVATE-SQL PRIVATE-PARAMS', '42P01', 'required_table_missing'),
    ('PRIVATE-UNKNOWN-DETAIL', None, 'database_error_unclassified'),
])
def test_diagnostic_never_exports_driver_exception_text(message, state, expected):
    from types import SimpleNamespace
    driver = Exception(message)
    driver.sqlstate = state
    safe = snapshot.safe_database_error(SimpleNamespace(orig=driver))
    assert safe['cause_code'] == expected
    assert 'PRIVATE' not in json.dumps(safe)


@pytest.mark.parametrize('host,provider,scope', [
    ('dpg-privatehost', 'render_postgres', 'private_or_internal_hostname'),
    ('dpg-privatehost.region-postgres.render.com', 'render_postgres', 'public_hostname_or_address'),
    ('db.privateproject.supabase.co', 'supabase_direct', 'public_hostname_or_address'),
    ('aws-0-private.pooler.supabase.com', 'supabase_pooler', 'public_hostname_or_address'),
    ('127.0.0.1', 'unidentified', 'local_host'),
])
def test_connection_hint_uses_fixed_labels_and_hides_connection_values(host, provider, scope):
    result = snapshot.public_connection_hint(f'postgresql+psycopg://PRIVATEUSER:PRIVATEPASS@{host}/PRIVATEDB')
    assert result['provider_hint'] == provider and result['host_scope_hint'] == scope
    assert host not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('suffix,required,expected', [
    ('', True, {'connect_timeout': 20, 'sslmode': 'require'}),
    ('?sslmode=disable', True, {'connect_timeout': 20, 'sslmode': 'require'}),
    ('?sslmode=verify-full', True, {'connect_timeout': 20, 'sslmode': 'verify-full'}),
    ('', False, {'connect_timeout': 20}),
])
def test_connection_options_apply_requested_timeout_and_preserve_stronger_tls(suffix, required, expected):
    options = snapshot.connection_options('postgresql+psycopg://user:password@db.invalid/test' + suffix,
                                          20, required)
    assert options == expected
