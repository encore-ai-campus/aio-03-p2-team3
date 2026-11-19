"""OAuth 콜백이 세션 쿠키 없이 대기 행을 찾는 공용 조회.

Calendar·Gmail 연결 모두 일회성 대기 행(`CalendarOAuthAttempt`)에서 완성한다.
프론트와 서버가 다른 사이트인 분리 배포에서도 콜백이 쿠키 의존 없이 동작한다."""
from hashlib import sha256

from sqlalchemy import select

from app.db.models import CalendarOAuthAttempt
from app.services.auth import utcnow


def digest(state: str) -> str:
    return sha256(state.encode()).hexdigest()


def pending_service(request, state: str | None) -> str | None:
    """미소비·유효한 대기 행의 서비스 이름(`gmail`/`calendar`). 없으면 None."""
    if not state:
        return None
    database = request.app.state.google_access.database
    with database.session() as session:
        return session.scalar(select(CalendarOAuthAttempt.service).where(
            CalendarOAuthAttempt.state_hash == digest(state),
            CalendarOAuthAttempt.consumed.is_(False),
            CalendarOAuthAttempt.expires_at > utcnow(),
        ).limit(1))
