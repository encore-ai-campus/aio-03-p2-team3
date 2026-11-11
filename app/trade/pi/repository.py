"""PI 전용 저장 범위. 엔진과 SQL 구현은 공통으로 사용한다."""
from app.trade.common.repository import SQLDocuments


def pi_repository(database, user_id: int) -> SQLDocuments:
    return SQLDocuments(database, user_id, "PI")
