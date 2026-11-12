"""가짜 Google 응답. `app/clients/gmail.py`의 `GoogleClient`와 같은 메서드를 가지며 실제 API를 부르지 않는다."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from app.clients.gmail import AccessToken, GoogleLogin, WatchResponse
from app.config import GOOGLE_SCOPES

ALL_SCOPES = sorted({
    "openid", "https://www.googleapis.com/auth/userinfo.email", *GOOGLE_SCOPES[2:],
})


def fake_login(sub="fake-sub-1", email="demo@example.invalid", refresh_token="fake-refresh-1",
               access_token="fake-access-1", scopes=ALL_SCOPES, expires_in=3600):
    return GoogleLogin(
        sub=sub, email=email, name="데모 사용자", access_token=access_token,
        refresh_token=refresh_token, expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scopes=list(scopes),
    )


class FakeGoogle:
    def __init__(self):
        self.calls = []
        self.logins = []          # exchange_code가 차례로 돌려줄 GoogleLogin
        self.refresh_error = None
        self.watch_error = None
        self.revoke_error = None
        self.history_ids = iter(str(n) for n in range(1000, 2000))
        self.refreshed = 0

    def authorization_url(self, state, code_verifier, consent=False):
        self.calls.append(("authorize", consent))
        query = urlencode({"state": state, "consent": int(consent)})
        return f"https://accounts.example.invalid/auth?{query}"

    def exchange_code(self, code, code_verifier):
        self.calls.append(("exchange", code, code_verifier))
        return self.logins.pop(0) if self.logins else fake_login()

    def refresh(self, refresh_token):
        self.calls.append(("refresh", refresh_token))
        if self.refresh_error:
            raise self.refresh_error
        self.refreshed += 1
        return AccessToken(f"fake-access-refreshed-{self.refreshed}", datetime.now(UTC) + timedelta(hours=1))

    def revoke(self, token):
        self.calls.append(("revoke", token))
        if self.revoke_error:
            raise self.revoke_error

    def watch(self, access_token, topic):
        self.calls.append(("watch", access_token, topic))
        if self.watch_error:
            raise self.watch_error
        return WatchResponse(next(self.history_ids), datetime.now(UTC) + timedelta(days=7))

    def stop(self, access_token):
        self.calls.append(("stop", access_token))

    def called(self, name):
        return [call for call in self.calls if call[0] == name]
