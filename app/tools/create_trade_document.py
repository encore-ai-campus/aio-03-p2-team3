"""create_trade_document: 무역서류(PI/PO/CI/PL) 초안을 만들어 저장한다(계약 15.5절, kekorea-port 3·6절).

파이프라인(계약 15.5절): `build_trade_catalog`(단가표 무역 행) → `apply_document_prices`
(PO 매입가·PI 판매가·CI는 첨부 PI 가격 그대로·PL 가격 없음) → `save_trade_document`
(`validate_and_calculate` 발행사 키 전달 + PL `packing_totals` 제안 + CI `ci_import_issues` 차단).
발행사·계좌는 문서 생성 때 복사한 스냅숏으로 남겨 설정 변경이 기존 문서를 바꾸지 않게 한다.
"""

from time import perf_counter

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.runlog.logger import current_database
from app.services.trade_docs import save_trade_document
from app.tools.base import ToolResult
from app.trade.ci_import import apply_document_prices
from app.trade.pricing import build_trade_catalog


class Input(BaseModel):
    user_id: int
    thread_id: str
    deal_terms: dict = Field(description="TradeDocTerms(계약 15.2절, doc_kind 키 포함)")
    company: dict | None = None  # 발행 회사 스냅샷(company_profiles)
    bank: dict | None = None  # PI용 계좌 스냅샷(대문자 6키 — 계약 15.7절)
    price_list: list[dict] = Field(default_factory=list)  # 무역 카탈로그 행(price_list_items 무역 행)
    run_id: str = ""
    deal_terms_id: int | None = None


@tool(args_schema=Input)
def create_trade_document(user_id, thread_id, deal_terms, company=None, bank=None,
                          price_list=None, run_id="", deal_terms_id=None) -> ToolResult:
    """카탈로그 가격·검증·계산을 거쳐 무역서류 초안을 저장한다. blocking이 있으면 needs_input."""
    started = perf_counter()
    try:
        doc_kind = str(deal_terms.get("document_type") or deal_terms.get("doc_kind") or "")
        if doc_kind not in {"PI", "PO", "CI", "PL"}:
            return ToolResult(ok=False, error_kind="invalid_input", source="code",
                              error_message="문서 종류는 PI·PO·CI·PL이어야 합니다")
        draft = {**deal_terms}
        draft["issuer"] = company or {}
        if doc_kind == "PI":
            draft["bank"] = bank  # PI만 계좌를 인쇄한다(계약 15.5절)
        # 원본(app_postprocess._extract_draft)과 같이 자리에서 고친다: PI·PO 경로는 반환값이
        # 없고(원본 apply_verified_eclado_prices도 마지막에 draft를 돌려주지 않는다) CI·PL 경로만
        # 같은 객체를 돌려준다. CI·PL에서 반환값을 쓰더라도 같은 draft 객체다.
        apply_document_prices(draft, build_trade_catalog(price_list or []))
        finalized = save_trade_document(
            current_database(), user_id=user_id, thread_id=thread_id, draft=draft,
            run_id=run_id, deal_terms_id=deal_terms_id)
        return ToolResult(ok=True, value=finalized, source="code",
                          duration_ms=int((perf_counter() - started) * 1000))
    except ValueError:
        return ToolResult(ok=False, error_kind="invalid_input", source="code",
                          error_message="무역서류 항목을 확인해 주세요")
    except Exception as error:
        # 예외 문자열에 메일 본문이 섞일 수 있어 종류만 남긴다.
        return ToolResult(ok=False, error_kind="internal", source="code",
                          error_message=f"무역서류 저장 실패 ({type(error).__name__})")
