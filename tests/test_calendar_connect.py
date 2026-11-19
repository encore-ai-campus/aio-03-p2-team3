"""#192: 실제 PostgreSQL과 가짜 Google의 서비스 격리·OAuth·갱신·실패 검사."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select

from app.auth.supabase import TokenVerifier
from app.clients.calendar import (CALENDAR_READ_SCOPES, CALENDAR_SCOPES, CalendarClient, CalendarDenied, CalendarDisabled,
                                 CalendarRejected)
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
        self.events = []          # list_events가 돌려줄 기간 내 일정
        self.list_error = None
        self.changed_events = {}
        self.conflicts = []
        self.change_after_timeout = False

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

    def list_events(self, access_token, calendar_id, *, time_min, time_max, include_details=False):
        self.calls.append(("list_events", access_token, calendar_id, time_min, time_max))
        if self.list_error:
            raise self.list_error
        return [dict(event) for event in (self.conflicts if include_details else self.events)]

    def event_for_change(self, token, event_id):
        self.calls.append(("event_for_change", token, event_id))
        event = self.changed_events.get(event_id)
        return dict(event) if event is not None else None

    def change_event(self, token, event_id, etag, new_time):
        self.calls.append(("change_event", token, event_id, etag, new_time))
        assert self.changed_events[event_id]["etag"] == etag
        if new_time is None:
            del self.changed_events[event_id]
        else:
            self.changed_events[event_id].update(**new_time, etag="2")
        if self.change_after_timeout:
            raise GoogleUnavailable("fake timeout after provider commit")


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


@contextmanager
def calendar_client(database_url, settings):
    jwks, gmail, calendar = FakeJwks(), FakeGoogle(), FakeCalendar()
    app = create_app(settings, google=gmail, calendar=calendar, supabase_auth=TokenVerifier(
        SUPABASE_URL, fetch_jwks=jwks.serve, secret_key="fake-secret", fetch_admin_user=jwks.admin_serve))
    with TestClient(app) as client:
        yield client, jwks, calendar


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://[", "http://127.0.0.1:3000"])
def test_calendar_connect_checks_browser_host_before_google_consent(database_url, origin):
    # 세션 쿠키는 호스트 단위라 localhost↔127.0.0.1 혼용 시 콜백에서 state를 잃는다.
    # Gmail과 같이 Google 동의 화면으로 가기 전에 막는다.
    settings = replace(settings_of(database_url), gmail_pubsub_topic="",
                       google_oauth_redirect_uri="http://127.0.0.1:8000/auth/google/callback")
    with calendar_client(database_url, settings) as (client, jwks, calendar):
        client.base_url = "http://127.0.0.1:3000"
        response = client.post("/api/calendar/connect", headers={**bearer(jwks.token()), "Origin": origin})
        if origin != "http://127.0.0.1:3000":
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "callback_host_mismatch"
            assert calendar.called("authorize") == calendar.called("exchange") == []
            assert not client.cookies.get("gq_session")
        else:
            assert response.status_code == 200, response.text
            assert len(calendar.called("authorize")) == 1


def test_calendar_callback_returns_to_configured_frontend_origin(database_url):
    # 별도 React 출처가 설정되면 콜백 결과는 그 출처로 돌아간다(빈 값이면 상대 주소).
    settings = replace(settings_of(database_url), gmail_pubsub_topic="",
                       frontend_origins="http://127.0.0.1:3000")
    with calendar_client(database_url, settings) as (client, jwks, _calendar):
        result = complete(client, start_calendar(client, jwks.token()))
        assert result.headers["location"] == "http://127.0.0.1:3000/app/settings?calendar=connected"


def test_calendar_callback_returns_to_root_frontend_base(database_url):
    # 분리 배포(루트 정적 사이트)에서는 기본 경로를 "/"로 지정해 /settings로 복귀한다.
    settings = replace(settings_of(database_url), gmail_pubsub_topic="",
                       frontend_origins="https://ui.example.invalid", frontend_base_path="/")
    with calendar_client(database_url, settings) as (client, jwks, _calendar):
        result = complete(client, start_calendar(client, jwks.token()))
        assert result.headers["location"] == "https://ui.example.invalid/settings?calendar=connected"


def test_calendar_only_refresh_disconnect_reconnect_and_encryption(connected_app):
    client, jwks, gmail, calendar = connected_app
    token = jwks.token()
    user_id = me(client, token)['user_id']
    finish(client, token)  # Pub/Sub 토픽 없이 Calendar만 연결
    profile = me(client, token)
    assert profile['calendar'] == {'connected': True, 'can_write': True}
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
    assert me(client, a)['gmail']['watch'] == 'active'
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


def test_free_busy_parses_intervals_and_keeps_empty_calendars(monkeypatch):
    start, end = datetime(2026, 11, 24, 9, tzinfo=timezone.utc), datetime(2026, 11, 24, 18, tzinfo=timezone.utc)
    def post(url, **kwargs):
        assert url.endswith('/freeBusy')
        assert kwargs['headers']['Authorization'] == 'Bearer fake-access'
        assert kwargs['json'] == {'timeMin': start.isoformat(), 'timeMax': end.isoformat(),
                                  'items': [{'id': 'primary'}, {'id': 'work@example.invalid'}]}
        return httpx.Response(200, json={'calendars': {
            'primary': {'busy': [{'start': '2026-11-24T10:00:00Z', 'end': '2026-11-24T10:30:00+09:00'}]},
            'work@example.invalid': {'errors': [{'domain': 'calendar', 'reason': 'notFound'}]},
        }})
    monkeypatch.setattr(httpx, 'post', post)
    snapshot = CalendarClient(settings_of('postgresql://fake')).free_busy(
        'fake-access', ['primary', 'work@example.invalid'], start, end)
    assert snapshot['primary']['busy'] == [(datetime(2026, 11, 24, 10, tzinfo=timezone.utc),
                                            datetime(2026, 11, 24, 10, 30, tzinfo=timezone(timedelta(hours=9))))]
    assert snapshot['primary']['errors'] == []
    assert snapshot['work@example.invalid'] == {'busy': [], 'errors': ['notFound']}


@pytest.mark.parametrize('status,payload,error', [
    (401, {}, TokenExpired),
    (403, {'error': {'errors': [{'reason': 'accessNotConfigured'}]}}, CalendarDisabled),
    (403, {'error': {'errors': [{'reason': 'userRateLimitExceeded'}]}}, GoogleUnavailable),
    (500, {}, GoogleUnavailable),
    (200, {'calendars': []}, GoogleUnavailable),
    (200, {'calendars': {'primary': {'busy': [{'start': '2026-11-24T10:00:00', 'end': '2026-11-24T11:00:00Z'}]}}},
     GoogleUnavailable),
])
def test_free_busy_http_errors_are_sanitized(monkeypatch, status, payload, error):
    def post(url, **kwargs):
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(error):
        CalendarClient(settings_of('postgresql://fake')).free_busy(
            'fake-access', ['primary'], datetime(2026, 11, 24, tzinfo=timezone.utc),
            datetime(2026, 11, 25, tzinfo=timezone.utc))


def test_insert_event_sends_body_and_returns_id(monkeypatch):
    start, end = datetime(2026, 11, 24, 10, tzinfo=timezone.utc), datetime(2026, 11, 24, 11, tzinfo=timezone.utc)
    def post(url, **kwargs):
        assert url == ('https://www.googleapis.com/calendar/v3/calendars/'
                       'work%40example.invalid/events')
        assert kwargs['json'] == {'summary': '가상 업무 회의',
                                  'start': {'dateTime': start.isoformat(), 'timeZone': 'Asia/Seoul'},
                                  'end': {'dateTime': end.isoformat(), 'timeZone': 'Asia/Seoul'},
                                  'attendees': [{'email': 'guest@example.invalid'}]}
        return httpx.Response(200, json={'id': 'event-1'})
    monkeypatch.setattr(httpx, 'post', post)
    event_id = CalendarClient(settings_of('postgresql://fake')).insert_event(
        'fake-access', 'work@example.invalid', summary='가상 업무 회의', start=start, end=end,
        timezone='Asia/Seoul', attendees=('guest@example.invalid',))
    assert event_id == 'event-1'


@pytest.mark.parametrize('status,payload,error,code', [
    (409, {'error': {'errors': [{'reason': 'conflict'}]}}, CalendarRejected, 'calendar_rejected'),
    (400, {}, CalendarRejected, 'calendar_rejected'),
    (401, {}, TokenExpired, None),
    (500, {}, GoogleUnavailable, None),
    (200, {}, GoogleUnavailable, None),
])
def test_insert_event_failures_are_classified(monkeypatch, status, payload, error, code):
    def post(url, **kwargs):
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(error) as caught:
        CalendarClient(settings_of('postgresql://fake')).insert_event(
            'fake-access', 'primary', summary='회의', start=datetime(2026, 11, 24, 10, tzinfo=timezone.utc),
            end=datetime(2026, 11, 24, 11, tzinfo=timezone.utc), timezone='Asia/Seoul')
    if code:
        assert caught.value.code == code


def test_get_event_returns_status_and_treats_missing_as_none(monkeypatch):
    client = CalendarClient(settings_of('postgresql://fake'))
    responses = [httpx.Response(200, json={'id': 'event-1', 'status': 'confirmed'}),
                 httpx.Response(404, json={}), httpx.Response(401, json={})]
    def get(url, **kwargs):
        assert url == ('https://www.googleapis.com/calendar/v3/calendars/'
                       'primary/events/event-1') and kwargs['params'] == {'fields': 'id,status'}
        return responses.pop(0)
    monkeypatch.setattr(httpx, 'get', get)
    assert client.get_event('fake-access', 'primary', 'event-1') == {'id': 'event-1', 'status': 'confirmed'}
    assert client.get_event('fake-access', 'primary', 'event-1') is None
    with pytest.raises(TokenExpired):
        client.get_event('fake-access', 'primary', 'event-1')


def test_list_events_paginates_and_normalizes_items(monkeypatch):
    seoul = timezone(timedelta(hours=9))
    start, end = datetime(2026, 11, 1, tzinfo=seoul), datetime(2026, 11, 30, 23, 59, 59, tzinfo=seoul)
    pages = [
        {'items': [{'id': 'event-1', 'summary': '주간 회의',
                    'start': {'dateTime': '2026-11-18T10:00:00+09:00'}, 'end': {'dateTime': '2026-11-18T11:00:00+09:00'}},
                   {'id': 'event-2', 'summary': None,
                    'start': {'date': '2026-11-20'}, 'end': {'date': '2026-11-21'}}],
         'nextPageToken': 'page-2'},
        {'items': [{'id': 'event-3', 'summary': '거래처 방문',
                    'start': {'dateTime': '2026-11-24T14:00:00Z'}, 'end': {'dateTime': '2026-11-24T15:00:00Z'}}]},
    ]
    def get(url, **kwargs):
        assert url == 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
        params = kwargs['params']
        assert params['timeMin'] == start.isoformat() and params['timeMax'] == end.isoformat()
        assert params['singleEvents'] == 'true' and params['orderBy'] == 'startTime'
        if 'pageToken' in params:
            assert params['pageToken'] == 'page-2'
            return httpx.Response(200, json=pages[1])
        return httpx.Response(200, json=pages[0])
    monkeypatch.setattr(httpx, 'get', get)
    found = CalendarClient(settings_of('postgresql://fake')).list_events(
        'fake-access', 'primary', time_min=start, time_max=end)
    assert found == [
        {'id': 'event-1', 'summary': '주간 회의', 'start': '2026-11-18T10:00:00+09:00',
         'end': '2026-11-18T11:00:00+09:00', 'all_day': False},
        {'id': 'event-2', 'summary': '', 'start': '2026-11-20', 'end': '2026-11-21', 'all_day': True},
        {'id': 'event-3', 'summary': '거래처 방문', 'start': '2026-11-24T14:00:00Z',
         'end': '2026-11-24T15:00:00Z', 'all_day': False},
    ]


@pytest.mark.parametrize('status,payload,error', [
    (401, {}, TokenExpired),
    (403, {'error': {'errors': [{'reason': 'userRateLimitExceeded'}]}}, GoogleUnavailable),
    (500, {}, GoogleUnavailable),
    (200, {'items': [{'id': 'event-1', 'start': {}, 'end': {}}]}, GoogleUnavailable),
])
def test_list_events_failures_are_sanitized(monkeypatch, status, payload, error):
    def get(url, **kwargs):
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'get', get)
    with pytest.raises(error):
        CalendarClient(settings_of('postgresql://fake')).list_events(
            'fake-access', 'primary', time_min=datetime(2026, 11, 1, tzinfo=timezone.utc),
            time_max=datetime(2026, 11, 30, tzinfo=timezone.utc))


def test_list_events_page_cap_fails_instead_of_truncating(monkeypatch):
    def get(url, **kwargs):
        return httpx.Response(200, json={'items': [], 'nextPageToken': 'more'})
    monkeypatch.setattr(httpx, 'get', get)
    with pytest.raises(GoogleUnavailable):
        CalendarClient(settings_of('postgresql://fake')).list_events(
            'fake-access', 'primary', time_min=datetime(2026, 11, 1, tzinfo=timezone.utc),
            time_max=datetime(2026, 11, 30, tzinfo=timezone.utc))


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


def test_calendar_events_requires_connection(connected_app):
    client, jwks, _gmail, calendar = connected_app
    response = client.get('/api/calendar/events', headers=bearer(jwks.token()),
                          params={'start': '2026-11-01T00:00:00+09:00', 'end': '2026-11-30T23:59:59+09:00'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'calendar_not_connected'
    assert calendar.called('list_events') == []


@pytest.mark.parametrize('start,end,code', [
    ('2026-11-01T00:00:00', '2026-11-30T00:00:00+09:00', 'invalid_range'),      # offset 없는 start
    ('not-a-date', '2026-11-30T00:00:00+09:00', 'invalid_range'),
    ('2026-11-30T00:00:00+09:00', '2026-11-01T00:00:00+09:00', 'invalid_range'),  # end가 start보다 앞
    ('2026-09-01T00:00:00+09:00', '2026-12-01T00:00:00+09:00', 'range_too_large'),
])
def test_calendar_events_validates_window(connected_app, start, end, code):
    client, jwks, _gmail, calendar = connected_app
    response = client.get('/api/calendar/events', headers=bearer(jwks.token()),
                          params={'start': start, 'end': end})
    assert response.status_code == 400
    assert response.json()['error']['code'] == code
    assert calendar.called('list_events') == []


def test_calendar_events_returns_primary_calendar_events(connected_app):
    client, jwks, _gmail, calendar = connected_app
    token = jwks.token()
    finish(client, token)
    calendar.events = [{'id': 'event-1', 'summary': '주간 회의', 'start': '2026-11-18T10:00:00+09:00',
                        'end': '2026-11-18T11:00:00+09:00', 'all_day': False}]
    response = client.get('/api/calendar/events', headers=bearer(token),
                          params={'start': '2026-11-01T00:00:00+09:00', 'end': '2026-11-30T23:59:59+09:00'})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['calendar_id'] == 'primary'
    assert payload['events'] == calendar.events
    [(kind, access, calendar_id, window_start, window_end)] = calendar.called('list_events')
    assert (kind, access, calendar_id) == ('list_events', 'calendar-access', 'primary')
    seoul = timezone(timedelta(hours=9))
    assert window_start == datetime(2026, 11, 1, tzinfo=seoul)
    assert window_end == datetime(2026, 11, 30, 23, 59, 59, tzinfo=seoul)


def test_calendar_events_refreshes_expired_token_before_listing(connected_app):
    client, jwks, _gmail, calendar = connected_app
    token = jwks.token()
    finish(client, token)
    user_id = me(client, token)['user_id']
    with client.app.state.database.session() as session:
        stored = session.get(CalendarToken, user_id)
        stored.expires_at = utcnow() - timedelta(minutes=1)
    calendar.events = [{'id': 'event-1', 'summary': '회의', 'start': '2026-11-18T10:00:00+09:00',
                        'end': '2026-11-18T11:00:00+09:00', 'all_day': False}]
    response = client.get('/api/calendar/events', headers=bearer(token),
                          params={'start': '2026-11-01T00:00:00+09:00', 'end': '2026-11-30T00:00:00+09:00'})
    assert response.status_code == 200, response.text
    assert calendar.called('refresh') == [('refresh', 'calendar-refresh')]
    assert calendar.called('list_events')[0][1] == 'fake-access-refreshed-1'


@pytest.mark.parametrize('error,code', [
    (GoogleUnavailable('공급자 장애'), 'google_unavailable'),
    (TokenExpired('갱신 필요'), 'token_expired'),
])
def test_calendar_events_maps_provider_failures(connected_app, error, code):
    client, jwks, _gmail, calendar = connected_app
    token = jwks.token()
    finish(client, token)
    calendar.list_error = error
    response = client.get('/api/calendar/events', headers=bearer(token),
                          params={'start': '2026-11-01T00:00:00+09:00', 'end': '2026-11-30T00:00:00+09:00'})
    assert response.status_code == 502
    assert response.json()['error']['code'] == code


@pytest.mark.parametrize("scenario,expected_code", [
    ("events", None), ("empty", None), ("capped", None),
    ("unconnected", "calendar_not_connected"), ("unavailable", "calendar_unavailable"),
    ("invalid_range", "invalid_range"),
])
def test_chat_reads_primary_calendar_agenda_without_approval(connected_app, monkeypatch, scenario, expected_code):
    from app.graph import wiring
    from langchain_core.messages import AIMessage

    client, jwks, _gmail, calendar = connected_app
    token = jwks.token()
    window = {"start": "2026-11-20T00:00:00+09:00", "end": "2026-11-21T00:00:00+09:00"}
    if scenario == "invalid_range":
        window["end"] = window["start"]
    messages_seen = []

    def choose(messages, _context):
        messages_seen.append(messages)
        if len(messages_seen) == 1:
            return AIMessage("", tool_calls=[{"id": "agenda", "name": "list_calendar_events",
                "args": window}]).model_dump()
        return AIMessage("조회 결과를 확인했습니다.").model_dump()

    original = wiring.make_workflow
    monkeypatch.setattr("app.main.make_workflow", lambda **kwargs: original(**{**kwargs, "choose": choose}))
    if scenario != "unconnected":
        finish(client, token)
    items = [
        {"id": "event-1", "summary": "전시회", "start": "2026-11-20", "end": "2026-11-21", "all_day": True},
        {"id": "event-2", "summary": "알파 미팅", "start": "2026-11-20T10:00:00+09:00",
         "end": "2026-11-20T11:00:00+09:00", "all_day": False},
    ]
    if scenario == "events":
        calendar.events = items
    if scenario == "capped":
        calendar.events = [{**items[1], "id": f"agenda-{index}"} for index in range(31)]
    if scenario == "unavailable":
        calendar.list_error = GoogleUnavailable("fake provider failure")

    response = client.post("/api/agent/conversations", headers=bearer(token),
                           json={"message": "내일 잡힌 일정과 시간을 알려줘."})
    assert response.status_code == 202, response.text
    state = client.get(f"/api/agent/conversations/{response.json()['id']}", headers=bearer(token)).json()
    assert state["waiting"] is None
    result, = state["results"]
    assert result["operation"] == "list_events"
    assert result["code"] == expected_code
    assert result["status"] == ("failed" if expected_code else "completed")
    if not expected_code:
        assert result["data"]["events"] == calendar.events[:30]
        assert result["data"]["total"] == len(calendar.events)
        assert result["data"]["calendar_id"] == "primary"
    calls = calendar.called("list_events")
    assert len(calls) == int(scenario not in {"unconnected", "invalid_range"})
    if calls:
        assert calls[0][1:3] == ("calendar-access", "primary")


def test_read_only_calendar_can_reauthorize_writes(connected_app):
    client, jwks, _gmail, calendar = connected_app
    token = jwks.token()
    calendar.logins.append(fake_login(scopes=CALENDAR_READ_SCOPES,
        access_token="read-access", refresh_token="read-refresh"))
    callback = complete(client, start_calendar(client, token))
    assert callback.headers["location"] == "/app/settings?calendar=write_scope_missing"
    assert me(client, token)["calendar"] == {"connected": True, "can_write": False}
    finish(client, token)
    assert calendar.called("authorize")[-1][-1] is True
    assert me(client, token)["calendar"] == {"connected": True, "can_write": True}


@pytest.mark.parametrize("scenario", [
    "move", "cancel", "all_day", "before_conflict", "after_conflict", "stale", "timeout", "timeout_cancel", "decline", "series", "unobserved", "no_write",
])
def test_calendar_change_workflow_rechecks_and_executes_only_once(database, scenario):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graph.calendar.adapters import ExistingCalendar
    from app.graph.wiring import make_workflow
    from app.services.auth import GoogleAccess, make_cipher

    end = "2042-11-22T11:00:00+09:00"
    event = {"id": "occurrence-1", "summary": "알파 정기 미팅", "start": "2042-11-22T10:00:00+09:00",
             "end": end, "all_day": scenario == "all_day"}
    if event["all_day"]:
        event.update(start="2042-11-22", end="2042-11-24")
    calendar = FakeCalendar()
    calendar.events = [event]
    calendar.changed_events[event["id"]] = {**event, "etag": "1", "recurring_instance": scenario != "series",
                                           "recurring_series": scenario == "series"}
    calendar.change_after_timeout = scenario in {"timeout", "timeout_cancel"}
    conflict = {**event, "id": "conflict", "summary": "다른 회의", "transparent": False}
    if scenario == "before_conflict":
        calendar.conflicts = [conflict]
    else:
        calendar.conflicts = [{**event, "transparent": False}, {**conflict, "transparent": True}]
    access = GoogleAccess(database, calendar, make_cipher(settings_of(str(database.engine.url))), "")
    with database.session() as session:
        session.add(CalendarToken(user_id=1, google_sub="fake-sub-1", scopes=list(
            CALENDAR_READ_SCOPES if scenario == "no_write" else CALENDAR_SCOPES),
            access_token_enc=access.cipher.encrypt("calendar-access"),
            refresh_token_enc=access.cipher.encrypt("calendar-refresh"), expires_at=utcnow() + timedelta(hours=1)))

    command = {"event_id": event["id"]}
    cancelling = scenario in {"cancel", "timeout_cancel"}
    tool_name = "prepare_cancel_calendar_event" if cancelling else "prepare_move_calendar_event"
    if not cancelling:
        command["new_start"] = "2042-11-25" if event["all_day"] else "2042-11-22T15:00:00+09:00"
    calls = [] if scenario == "unobserved" else [("list_calendar_events", {
        "start": "2042-11-22T00:00:00+09:00", "end": "2042-11-23T00:00:00+09:00"})]
    calls += [(tool_name, command)]

    def choose(_messages, _context):
        if calls:
            name, args = calls.pop(0)
            return AIMessage("", tool_calls=[{"id": name, "name": name, "args": args}]).model_dump()
        return AIMessage("결과를 확인했습니다.").model_dump()

    workflow = make_workflow(database=database, calendar=ExistingCalendar(access),
                             checkpointer=InMemorySaver(), interactive=True, choose=choose)
    args = {"actor_id": 1, "thread_id": f"calendar-{scenario}"}
    state = workflow.start(**args, request="알파 일정 확인")
    assert not calendar.called("change_event")
    waiting = workflow.snapshot(**args)["waiting"]
    blocked = {"before_conflict": "calendar_move_conflict", "unobserved": "calendar_event_lookup_required",
               "no_write": "calendar_write_required", "series": "calendar_select_occurrence"}
    if scenario in blocked:
        assert waiting is None
        assert list(state["results"].values())[-1]["code"] == blocked[scenario]
        return

    action = waiting["action"]
    assert action["payload"]["event"]["recurring_instance"]
    if scenario == "all_day":
        assert action["payload"]["new_time"]["end"] == "2042-11-27"
    elif not cancelling:
        assert action["payload"]["new_time"]["end"] == "2042-11-22T16:00:00+09:00"
    response = {"action_id": action["id"], "content_hash": waiting["content_hash"],
                "decision": "cancel" if scenario == "decline" else "approve"}
    if scenario == "stale":
        calendar.changed_events[event["id"]]["etag"] = "another-user-edit"
    if scenario == "after_conflict":
        calendar.conflicts = [conflict]
    finished = workflow.resume(**args, response=response)
    result = finished["results"][action["task_id"]]
    if scenario in {"stale", "after_conflict"}:
        assert result["code"] == ("calendar_event_changed" if scenario == "stale" else "calendar_move_conflict")
        assert not calendar.called("change_event")
        return
    if scenario == "decline":
        assert result["status"] == "cancelled"
        assert not calendar.called("change_event")
        return
    if scenario in {"timeout", "timeout_cancel"}:
        assert result["status"] == "unknown"
        result = workflow.recover(**args)["results"][action["task_id"]]
    assert result["status"] == "completed"
    assert result["data"]["calendar_outcome"] == ("cancelled" if cancelling else "moved")
    workflow.resume(**args, response=response)
    assert len(calendar.called("change_event")) == 1


def test_calendar_http_mutation_uses_etag_and_occurrence_id(monkeypatch):
    from app.clients.calendar import CalendarChanged

    captured = []

    def patch(url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(200, json={})

    monkeypatch.setattr("app.clients.calendar.httpx.patch", patch)
    google = CalendarClient(settings_of("postgresql://fixture"))
    event_id = "series_20421122T010000Z"
    google.change_event("fake-token", event_id, '"v1"', {
        "start": "2042-11-22T15:00:00+09:00", "end": "2042-11-22T16:00:00+09:00",
        "timezone": "Asia/Seoul", "all_day": False,
    })
    url, data = captured[0]
    assert url.endswith("/calendars/primary/events/" + event_id)
    assert data["headers"]["If-Match"] == '"v1"'
    assert data["json"]["start"]["timeZone"] == "Asia/Seoul"
    monkeypatch.setattr("app.clients.calendar.httpx.delete", lambda *a, **kw: httpx.Response(412))
    with pytest.raises(CalendarChanged):
        google.change_event("fake-token", event_id, '"v1"', None)
