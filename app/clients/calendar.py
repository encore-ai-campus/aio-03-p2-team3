"""읽기 전용 Calendar OAuth와 연결 확인. 일정 본문을 읽거나 기록하지 않는다."""
import httpx

from app.clients.gmail import (
    GoogleClient, GoogleError, GoogleUnavailable, HTTP_TIMEOUT_SECONDS,
    TokenExpired, normalize_scopes,
)

CALENDAR_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.readonly")


class CalendarDenied(GoogleError):
    code = "scope_missing"


class CalendarDisabled(GoogleError):
    code = "api_disabled"


def missing_calendar_scopes(granted):
    return normalize_scopes(CALENDAR_SCOPES) - normalize_scopes(granted)


class CalendarClient(GoogleClient):
    scopes = CALENDAR_SCOPES

    def authorization_url(self, state, code_verifier, consent=False):
        options = {"access_type": "offline", "include_granted_scopes": "false"}
        if consent:
            options["prompt"] = "consent"
        url, _ = self._flow(code_verifier, state).authorization_url(**options)
        return url

    def check_calendars(self, access_token):
        try:
            response = httpx.get(
                "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                params={"maxResults": 1, "fields": "items(id)"},
                headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise GoogleUnavailable("calendar_transport") from error
        if response.status_code == 401:
            raise TokenExpired("calendar_unauthorized")
        if response.status_code == 403:
            try:
                payload = response.json().get("error", {})
                reasons = {entry.get("reason") for entry in payload.get("errors", [])}
                reasons.update(entry.get("reason") for entry in payload.get("details", []))
            except (ValueError, TypeError, AttributeError):
                reasons = set()
            if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
                raise CalendarDisabled("calendar_disabled")
            if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded",
                          "quotaExceeded", "RATE_LIMIT_EXCEEDED"}:
                raise GoogleUnavailable("calendar_quota")
            raise CalendarDenied("calendar_forbidden")
        if response.status_code != 200:
            raise GoogleUnavailable("calendar_http")
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                raise ValueError()
        except ValueError as error:
            raise GoogleUnavailable("calendar_response") from error
