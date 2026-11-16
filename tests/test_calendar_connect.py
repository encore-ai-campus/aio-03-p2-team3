"""#192: 실제 PostgreSQL과 가짜 Google의 서비스 격리·OAuth·갱신·실패 검사."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select

from app.auth.supabase import TokenVerifier
from app.clients.calendar import CALENDAR_SCOPES, CalendarClient, CalendarDenied, CalendarDisabled
from app.clients.gmail import GoogleError, GoogleUnavailable, TokenExpired
from app.db.models import CalendarOAuthAttempt, CalendarToken, GoogleToken
from app.main import create_app
from app.services.auth import utcnow
from tests.fakes.google import FakeGoogle, fake_login
from tests.test_gmail_connect import bearer, complete, me, settings_of, start_connect, state_of
from tests.test_supabase_auth import FakeJwks, SUPABASE_URL


class FakeCalendar(FakeGoogle):
    def __init__(self):
        super().__init__()
        self.check_error = None
        self.exchange_error = None
        self.verifiers = {}

    def authorization_url(self, state, code_verifier, consent=False):
        self.verifiers[state] = code_verifier
        return super().authorization_url(state, code_verifier, consent)

    def exchange_code(self, code, code_verifier):
        if self.exchange_error:
            raise self.exchange_error
        assert code_verifier in self.verifiers.values()  # 저장된 PKCE 검증값이 실제 교환까지 전달됨
        self.calls.append(("exchange", code, code_verifier))
        return self.logins.pop(0) if self.logins else fake_login(scopes=CALENDAR_SCOPES,
            access_token="calendar-access", refresh_token="calendar-refresh")

    def check_calendars(self, token):
        self.calls.append(("calendars", token))
        if self.check_error:
            raise self.check_error


@pytest.fixture
def connected_app(database_url):
    jwks, gmail, calendar = FakeJwks(), FakeGoogle(), FakeCalendar()
    settings = replace(settings_of(database_url), gmail_pubsub_topic="")
    app = create_app(settings, google=gmail, calendar=calendar, supabase_auth=TokenVerifier(
        SUPABASE_URL, fetch_jwks=jwks.serve, secret_key="fake-secret", fetch_admin_user=jwks.admin_serve))
    with TestClient(app) as client:
        yield client, jwks, gmail, calendar


def start_calendar(client, token):
    response = client.post('/api/calendar/connect', headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()['authorization_url']


def finish(client, token):
    response = complete(client, start_calendar(client, token))
    assert response.headers['location'] == '/app/settings?calendar=connected'


def test_calendar_only_refresh_disconnect_reconnect_and_encryption(connected_app):
    client, jwks, gmail, calendar = connected_app
    token = jwks.token()
    user_id = me(client, token)['user_id']
    finish(client, token)  # Pub/Sub 토픽 없이 Calendar만 연결
    profile = me(client, token)
    assert profile['calendar'] == {'connected': True}
    assert profile['gmail']['connected'] is False and gmail.calls == []
    with client.app.state.database.session() as session:
        stored = session.get(CalendarToken, user_id)
        cipher = client.app.state.calendar_access.cipher
        assert cipher.decrypt(stored.refresh_token_enc) == 'calendar-refresh'
        assert 'calendar-refresh' not in stored.refresh_token_enc
        stored.expires_at = utcnow() - timedelta(minutes=1)
        assert session.get(GoogleToken, user_id) is None
    assert me(client, token)['calendar']['connected'] is True
    assert calendar.called('refresh') == [('refresh', 'calendar-refresh')]
    assert client.post('/api/calendar/disconnect', headers=bearer(token)).json() == {'connected': False}
    assert me(client, token)['calendar'] == {'connected': False}
    assert not calendar.called('revoke')
    finish(client, token)
    assert me(client, token)['calendar']['connected']


def test_calendar_state_cookie_replay_expiry_and_cross_flow(connected_app):
    client, jwks, gmail, calendar = connected_app
    token = jwks.token()
    url = start_calendar(client, token)
    old_cookie = client.cookies.get('gq_session')
    finish_result = complete(client, url)
    assert finish_result.headers['location'].endswith('calendar=connected')
    client.cookies.set('gq_session', old_cookie)
    assert complete(client, url).headers['location'].endswith('calendar=login_failed')
    assert len(calendar.called('exchange')) == 1
    url = start_calendar(client, token)
    assert client.get('/auth/google/callback', params={'state': 'wrong', 'code': 'x'},
                      follow_redirects=False).headers['location'].endswith('calendar=login_failed')
    with client.app.state.database.session() as session:
        assert session.get(CalendarOAuthAttempt, sha256(state_of(url).encode()).hexdigest()) is None
    url = start_calendar(client, token)
    with client.app.state.database.session() as session:
        attempt = session.get(CalendarOAuthAttempt, sha256(state_of(url).encode()).hexdigest())
        attempt.expires_at = utcnow() - timedelta(seconds=1)
    assert complete(client, url).headers['location'].endswith('calendar=expired')
    # Gmail/Calendar가 같은 callback을 써도 서로의 state로 코드 교환하지 않는다.
    calendar_url = start_calendar(client, token)
    client.app.state.settings = settings_of(client.app.state.settings.database_url)
    start_connect(client, token)
    assert complete(client, calendar_url).headers['location'].endswith('gmail=login_failed')
    gmail_url = start_connect(client, token)
    start_calendar(client, token)
    assert complete(client, gmail_url).headers['location'].endswith('calendar=login_failed')
    assert not gmail.called('exchange') and len(calendar.called('exchange')) == 1


@pytest.mark.parametrize('failure,notice', [
    ('cancel', 'cancelled'), ('other', 'different_account'), ('scope', 'scope_missing'),
    ('expired', 'token_expired'), ('pkce', 'login_failed'), ('outage', 'google_unavailable'),
    ('disabled', 'api_disabled'), ('denied', 'scope_missing'),
])
def test_failed_calendar_connection_never_stores_token(connected_app, failure, notice):
    client, jwks, gmail, calendar = connected_app
    token = jwks.token()
    user_id = me(client, token)['user_id']
    if failure == 'other': calendar.logins.append(fake_login(sub='other', scopes=CALENDAR_SCOPES))
    if failure == 'scope': calendar.logins.append(fake_login(scopes=['openid', 'email']))
    if failure == 'expired': calendar.logins.append(fake_login(scopes=CALENDAR_SCOPES, expires_in=-1))
    if failure == 'pkce': calendar.exchange_error = GoogleError('invalid_grant')
    if failure == 'outage': calendar.check_error = GoogleUnavailable('outage')
    if failure == 'disabled': calendar.check_error = CalendarDisabled('disabled')
    if failure == 'denied': calendar.check_error = CalendarDenied('denied')
    url = start_calendar(client, token)
    response = (client.get('/auth/google/callback', params={'state': state_of(url), 'error': 'access_denied'},
                           follow_redirects=False) if failure == 'cancel' else complete(client, url))
    assert response.headers['location'] == '/app/settings?calendar=' + notice
    with client.app.state.database.session() as session:
        assert session.get(CalendarToken, user_id) is None
    assert not gmail.calls


def test_refresh_missing_retries_consent_only_once_and_checks_account_first(connected_app):
    client, jwks, _, calendar = connected_app
    token = jwks.token()
    calendar.logins += [fake_login(scopes=CALENDAR_SCOPES, refresh_token=None)] * 2
    retry = complete(client, start_calendar(client, token))
    assert parse_qs(urlparse(retry.headers['location']).query)['consent'] == ['1']
    assert complete(client, retry.headers['location']).headers['location'].endswith('calendar=refresh_missing')
    assert len(calendar.called('authorize')) == 2
    calendar.logins.append(fake_login(sub='other', scopes=CALENDAR_SCOPES, refresh_token=None))
    assert complete(client, start_calendar(client, token)).headers['location'].endswith('calendar=different_account')
    calendar.logins += [fake_login(scopes=CALENDAR_SCOPES, refresh_token=None), fake_login(scopes=CALENDAR_SCOPES)]
    retry = complete(client, start_calendar(client, token))
    assert complete(client, retry.headers['location']).headers['location'].endswith('calendar=connected')


def test_user_isolation_shared_grant_and_service_disconnect(connected_app):
    client, jwks, gmail, calendar = connected_app
    a, b = jwks.token(), jwks.token()
    # b는 다른 검증된 Google 계정
    b_sub = uuid4()
    jwks.with_google_identity(b_sub, 'google-b')
    b = jwks.token(sub=b_sub)
    finish(client, a)
    assert me(client, b)['calendar']['connected'] is False
    calendar.logins.append(fake_login(sub='google-b', scopes=CALENDAR_SCOPES, refresh_token='b-refresh'))
    finish(client, b)
    assert client.post('/api/calendar/disconnect', headers=bearer(b)).status_code == 200
    assert me(client, a)['calendar']['connected'] is True
    assert me(client, b)['calendar']['connected'] is False
    client.app.state.settings = settings_of(client.app.state.settings.database_url)
    assert complete(client, start_connect(client, a)).headers['location'].endswith('gmail=connected')
    assert me(client, a)['gmail']['connected'] and me(client, a)['calendar']['connected']
    client.post('/api/calendar/disconnect', headers=bearer(a))
    assert me(client, a)['gmail']['connected'] and not gmail.called('revoke')
    finish(client, a)
    client.post('/api/gmail/logout', headers=bearer(a))
    assert me(client, a)['calendar']['connected']
    assert me(client, a)['gmail']['watch'] == 'stopped'
    # Gmail revoke가 같은 클라이언트 grant를 폐기한 공급자 응답
    calendar.check_error = TokenExpired('shared_grant_revoked')
    client.post('/api/gmail/disconnect', headers=bearer(a))
    assert gmail.called('revoke')
    assert me(client, a)['calendar'] == {'connected': False}


def test_status_outage_preserves_tokens_but_revocation_clears_only_calendar(connected_app):
    client, jwks, _, calendar = connected_app
    token = jwks.token()
    finish(client, token)
    user_id = me(client, token)['user_id']
    calendar.check_error = GoogleUnavailable('outage')
    assert me(client, token)['calendar'] == {'connected': False, 'error': 'google_unavailable'}
    with client.app.state.database.session() as session:
        assert session.get(CalendarToken, user_id)
        session.get(CalendarToken, user_id).expires_at = utcnow() - timedelta(minutes=1)
    calendar.check_error = None
    calendar.refresh_error = TokenExpired('invalid_grant')
    assert me(client, token)['calendar'] == {'connected': False}
    with client.app.state.database.session() as session:
        assert session.get(CalendarToken, user_id) is None


def test_calendar_requires_bearer_identity_and_configuration(connected_app):
    client, jwks, _, _ = connected_app
    for action in ('connect', 'disconnect'):
        assert client.post('/api/calendar/' + action).status_code == 401
        assert client.post('/api/calendar/' + action, headers=bearer('invalid')).status_code == 401
    subject = uuid4()
    token = jwks.token(sub=subject)
    jwks.admin_users[str(subject)] = {'identities': []}
    assert client.post('/api/calendar/connect', headers=bearer(token)).status_code == 409
    client.app.state.settings = replace(client.app.state.settings, google_oauth_client_secret='')
    assert client.post('/api/calendar/connect', headers=bearer(jwks.token())).status_code == 503


def test_real_calendar_client_requests_only_read_scopes_and_pkce(monkeypatch):
    settings = settings_of('postgresql://fake')
    calendar = CalendarClient(settings)
    url = calendar.authorization_url('fake-state', 'v' * 64)
    query = parse_qs(urlparse(url).query)
    assert set(query['scope'][0].split()) == set(CALENDAR_SCOPES)
    assert query['code_challenge_method'] == ['S256'] and 'code_challenge' in query
    assert query['include_granted_scopes'] == ['false']
    assert query['access_type'] == ['offline']
    assert query['redirect_uri'] == [settings.google_oauth_redirect_uri]


@pytest.mark.parametrize('status,payload,error', [
    (200, {'items': []}, None), (401, {}, TokenExpired),
    (403, {'error': {'errors': [{'reason': 'accessNotConfigured'}]}}, CalendarDisabled),
    (403, {'error': {'details': [{'reason': 'SERVICE_DISABLED'}]}}, CalendarDisabled),
    (403, {}, CalendarDenied), (500, {}, GoogleUnavailable), (200, [], GoogleUnavailable),
])
def test_calendar_list_http_errors_are_sanitized(monkeypatch, status, payload, error):
    def get(url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer fake-access'
        assert kwargs['params'] == {'maxResults': 1, 'fields': 'items(id)'}
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'get', get)
    client = CalendarClient(settings_of('postgresql://fake'))
    if error:
        with pytest.raises(error): client.check_calendars('fake-access')
    else:
        client.check_calendars('fake-access')


def test_disconnecting_during_provider_check_cannot_restore_token(connected_app):
    client, jwks, _, calendar = connected_app
    token = jwks.token()
    url = start_calendar(client, token)
    def check(_):
        assert client.post('/api/calendar/disconnect', headers=bearer(token)).status_code == 200
    calendar.check_calendars = check
    assert complete(client, url).headers['location'].endswith('calendar=expired')
    assert me(client, token)['calendar'] == {'connected': False}


def test_pkce_mismatch_is_rejected_by_provider_without_saving(connected_app):
    client, jwks, _, calendar = connected_app
    token = jwks.token()
    url = start_calendar(client, token)
    with client.app.state.database.session() as session:
        attempt = session.get(CalendarOAuthAttempt, sha256(state_of(url).encode()).hexdigest())
        attempt.verifier_enc = client.app.state.calendar_access.cipher.encrypt('wrong-verifier')
    def exchange(_, verifier):
        if verifier not in calendar.verifiers.values():
            raise GoogleError('invalid_grant')
        raise AssertionError('expected mismatching PKCE verifier')
    calendar.exchange_code = exchange
    assert complete(client, url).headers['location'].endswith('calendar=login_failed')
    assert me(client, token)['calendar'] == {'connected': False}


@pytest.mark.parametrize('error,connected_error,preserved', [
    (CalendarDisabled('disabled'), 'api_disabled', True),
    (GoogleUnavailable('outage'), 'google_unavailable', True),
    (CalendarDenied('permission'), None, False),
    (TokenExpired('revoked'), None, False),
])
def test_status_revalidation_preserves_only_recoverable_tokens(connected_app, error, connected_error, preserved):
    client, jwks, _, calendar = connected_app
    token = jwks.token()
    finish(client, token)
    user_id = me(client, token)['user_id']
    calendar.check_error = error
    expected = {'connected': False}
    if connected_error: expected['error'] = connected_error
    assert me(client, token)['calendar'] == expected
    with client.app.state.database.session() as session:
        assert bool(session.get(CalendarToken, user_id)) == preserved


def test_calendar_tables_are_server_only_and_existing_gmail_tokens_unchanged(connected_app):
    from sqlalchemy import text
    client, jwks, gmail, _ = connected_app
    token = jwks.token()
    client.app.state.settings = settings_of(client.app.state.settings.database_url)
    assert complete(client, start_connect(client, token)).headers['location'].endswith('gmail=connected')
    user_id = me(client, token)['user_id']
    with client.app.state.database.session() as session:
        before = session.get(GoogleToken, user_id)
        before_values = (before.access_token_enc, before.refresh_token_enc, before.scopes)
        flags = session.execute(text("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN "
                                     "('calendar_tokens', 'calendar_oauth_attempts')")).all()
        assert len(flags) == 2 and all(flag for _, flag in flags)
    finish(client, token)
    client.post('/api/calendar/disconnect', headers=bearer(token))
    with client.app.state.database.session() as session:
        after = session.get(GoogleToken, user_id)
        assert (after.access_token_enc, after.refresh_token_enc, after.scopes) == before_values
    assert not gmail.called('revoke')
