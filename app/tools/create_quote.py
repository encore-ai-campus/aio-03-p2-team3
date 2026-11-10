"""create_quote: 합의 단가·단가표로 계산하고 초안을 저장한다."""

from time import perf_counter

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Quote, User, utcnow
from app.graph.state import DealTerms
from app.quote.calc import build_draft
from app.runlog.logger import current_database
from app.tools.base import ToolResult


class Input(BaseModel):
    user_id: int
    thread_id: str
    deal_terms: DealTerms
    company: dict | None = None
    price_list: list[dict] = Field(default_factory=list)


@tool(args_schema=Input)
def create_quote(user_id, thread_id, deal_terms, company=None, price_list=None) -> ToolResult:
    """코드로 견적서를 계산·저장한다. 단가가 없으면 사용자 입력을 기다린다."""
    started = perf_counter()
    try:
        today = utcnow().date()
        # Postgres는 사용자 행 잠금으로 번호 생성을 직렬화한다. SQLite는 유일 제약으로 재시도.
        for attempt in range(3):
            try:
                with current_database().session() as session:
                    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
                    if user is None:
                        return ToolResult(ok=False, error_kind="not_found", source="code",
                                          error_message="사용자를 찾을 수 없습니다")
                    prefix = f"Q-{today:%Y%m%d}-"
                    numbers = session.scalars(select(Quote.quote_no).where(
                        Quote.user_id == user_id, Quote.quote_no.startswith(prefix),
                    )).all()
                    sequence = max((int(number[len(prefix):]) for number in numbers), default=0) + 1
                    draft = build_draft(deal_terms, company, price_list or [],
                                        quote_no=f"{prefix}{sequence:03d}", quote_date=today)
                    row = Quote(user_id=user_id, thread_id=thread_id, run_id="",
                                quote_no=draft["quote_no"], draft=draft, status=draft["status"])
                    session.add(row)
                    session.flush()
                    draft = {**draft, "quote_id": row.id}
                    row.draft = draft
                return ToolResult(ok=True, value=draft, source="code",
                                  duration_ms=int((perf_counter() - started) * 1000))
            except IntegrityError:
                if attempt == 2:
                    raise
    except ValueError:
        return ToolResult(ok=False, error_kind="invalid_input", source="code",
                          error_message="견적서의 거래 항목과 단가를 확인해 주세요")
    except Exception as error:
        return ToolResult(ok=False, error_kind="internal", source="code",
                          error_message=f"견적서 저장 실패 ({type(error).__name__})")
