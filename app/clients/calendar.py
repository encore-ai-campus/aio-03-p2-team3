"""Calendar OAuth와 연결 확인, 일정 조회·등록 호출기."""
from datetime import datetime
from urllib.parse import quote
import httpx

from app.clients.gmail import (
    GoogleClient, GoogleError, GoogleUnavailable, HTTP_TIMEOUT_SECONDS,
    TokenExpired, normalize_scopes,
)

CALENDAR_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.readonly")
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars"
FREE_BUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
LIST_EVENTS_MAX_PAGES = 12  # 250건×12페이지. 상한을 넘으면 잘린 목록 대신 실패한다.
FORBIDDEN_SERVICE_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
FORBIDDEN_QUOTA_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded",
                                     "quotaExceeded", "RATE_LIMIT_EXCEEDED"})


class CalendarDenied(GoogleError):
    code = "scope_missing"


class CalendarRejected(GoogleError):
    """일정 등록 거부(400·409 등). 재시도하지 않는 확정 실패다."""

    code = "calendar_rejected"


class CalendarDisabled(GoogleError):
    code = "api_disabled"


def missing_calendar_scopes(granted):
    return normalize_scopes(CALENDAR_SCOPES) - normalize_scopes(granted)


def _forbidden_reasons(response):
    try:
        payload = response.json().get("error", {})
        reasons = {entry.get("reason") for entry in payload.get("errors", [])}
        reasons.update(entry.get("reason") for entry in payload.get("details", []))
    except (ValueError, TypeError, AttributeError):
        reasons = set()
    return reasons


def _raise_calendar_error(status_code, response):
    """모든 Calendar 호출이 같은 오류 체계를 공유한다(check_calendars와 동일)."""
    if status_code == 401:
        raise TokenExpired("calendar_unauthorized")
    if status_code == 403:
        reasons = _forbidden_reasons(response)
        if reasons & FORBIDDEN_SERVICE_REASONS:
            raise CalendarDisabled("calendar_disabled")
        if reasons & FORBIDDEN_QUOTA_REASONS:
            raise GoogleUnavailable("calendar_quota")
        raise CalendarDenied("calendar_forbidden")
    if status_code != 200:
        raise GoogleUnavailable("calendar_http")


def _parse_instant(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("instant_without_offset")
    return moment


def _normalize_event(item):
    """화면이 쓰는 최소 필드. 시각은 Google 원문(offset dateTime 또는 종일 date)을 변환 없이 전달한다."""
    start, end = item.get("start") or {}, item.get("end") or {}
    if "date" in start or "date" in end:
        begin, finish, all_day = start.get("date"), end.get("date"), True
    else:
        begin, finish, all_day = start.get("dateTime"), end.get("dateTime"), False
    if not isinstance(begin, str) or not isinstance(finish, str):
        raise ValueError("event_time_missing")
    return {"id": item["id"], "summary": item.get("summary") or "",
            "start": begin, "end": finish, "all_day": all_day}


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
        _raise_calendar_error(response.status_code, response)
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                raise ValueError()
        except ValueError as error:
            raise GoogleUnavailable("calendar_response") from error

    def free_busy(self, access_token, calendar_ids, start, end):
        """캘린더별 바쁜 구간과 조회 오류. 빈 캘린더도 키로 남긴다(완전성은 노드가 검사한다)."""
        try:
            response = httpx.post(
                FREE_BUSY_URL,
                json={"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                      "items": [{"id": calendar_id} for calendar_id in calendar_ids]},
                headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise GoogleUnavailable("calendar_transport") from error
        _raise_calendar_error(response.status_code, response)
        try:
            calendars = response.json()["calendars"]
            if not isinstance(calendars, dict):
                raise ValueError()
            snapshot = {}
            for calendar_id, entry in calendars.items():
                busy = [(_parse_instant(item["start"]), _parse_instant(item["end"]))
                        for item in entry.get("busy", [])]
                errors = [item.get("reason") for item in entry.get("errors", [])]
                snapshot[calendar_id] = {"busy": busy, "errors": errors}
        except (ValueError, TypeError, KeyError) as error:
            raise GoogleUnavailable("calendar_response") from error
        return snapshot

    def list_events(self, access_token, calendar_id, *, time_min, time_max):
        """기간 내 일정 목록(읽기 전용). 종일 일정은 date, 나머지는 offset dateTime을 그대로 돌려준다."""
        events, page_token = [], None
        for _ in range(LIST_EVENTS_MAX_PAGES):
            params = {"timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(),
                      "singleEvents": "true", "orderBy": "startTime", "maxResults": 250,
                      "fields": "nextPageToken,items(id,summary,start,end)"}
            if page_token:
                params["pageToken"] = page_token
            try:
                response = httpx.get(
                    f"{EVENTS_URL}/{quote(calendar_id)}/events", params=params,
                    headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                raise GoogleUnavailable("calendar_transport") from error
            _raise_calendar_error(response.status_code, response)
            try:
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                    raise ValueError()
                events.extend(_normalize_event(item) for item in data["items"])
            except (ValueError, TypeError, KeyError) as error:
                raise GoogleUnavailable("calendar_response") from error
            page_token = data.get("nextPageToken")
            if not page_token:
                return events
        raise GoogleUnavailable("calendar_response")  # 페이지 상한 초과는 잘린 목록 대신 실패

    def insert_event(self, access_token, calendar_id, *, summary, start, end, timezone, attendees=(),
                     event_id=None):
        """일정을 등록하고 이벤트 ID를 돌려준다. 거부(4xx)는 확정 실패다.

        event_id를 넣으면 그 ID로 등록한다(같은 승인의 재실행·타임아웃 뒤 확인에 쓰는
        결정적 ID. 어댑터가 만들고 Google은 같은 승인의 재시도를 같은 이벤트로 받는다)."""
        try:
            response = httpx.post(
                f"{EVENTS_URL}/{quote(calendar_id)}/events",
                json={"summary": summary,
                      **({"id": event_id} if event_id else {}),
                      "start": {"dateTime": start.isoformat(), "timeZone": timezone},
                      "end": {"dateTime": end.isoformat(), "timeZone": timezone},
                      **({"attendees": [{"email": address} for address in attendees]} if attendees else {})},
                headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise GoogleUnavailable("calendar_transport") from error
        if 400 <= response.status_code < 500 and response.status_code not in (401, 403):
            raise CalendarRejected("일정 등록이 거부됐다")
        _raise_calendar_error(response.status_code, response)
        try:
            event_id = response.json()["id"]
            if not isinstance(event_id, str) or not event_id:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as error:
            raise GoogleUnavailable("calendar_response") from error
        return event_id

    def get_event(self, access_token, calendar_id, event_id):
        """등록 확인. 삭제된 일정은 None을 돌려준다."""
        try:
            response = httpx.get(
                f"{EVENTS_URL}/{quote(calendar_id)}/events/{quote(event_id)}",
                params={"fields": "id,status"},
                headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise GoogleUnavailable("calendar_transport") from error
        if response.status_code == 404:
            return None
        _raise_calendar_error(response.status_code, response)
        try:
            data = response.json()
            if not isinstance(data.get("id"), str) or not isinstance(data.get("status"), str):
                raise ValueError()
        except (ValueError, AttributeError) as error:
            raise GoogleUnavailable("calendar_response") from error
        return {"id": data["id"], "status": data["status"]}
