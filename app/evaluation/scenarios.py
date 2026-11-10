"""시험 시나리오(계획 17절). 시험 메일은 모두 지어낸 내용이다(실제 회사·사람·주소 없음).

시나리오마다 정하는 것(측정 전에 정한 판정 기준, `docs/TEST_REPORT.md` 3·4절과 같다):
- `expect`: 완료 조건(종료 이유·후보 종류와 개수·확인 필요 표시·재질문 항목·견적서·금지 표현·승인 결과)과
  정답 도구 조합(`tools`).
- `inject`: 실제 API로 돌릴 때도 넣는 준비된 응답·고의 실패. LLM 출력 형식 이름(스키마 이름)마다 앞에서부터
  꺼내 쓴다. 값이 dict면 준비된 응답, 함수면 그 함수가 만든 예외(고의 실패)다.
- `fake`: 가짜 LLM으로 돌릴 때만 쓰는 준비된 응답(같은 방식, 마지막 하나는 계속 쓴다). 반복마다 응답을 바꾸려면
  dict 목록을 주고, 반복 번호로 돌아가며 고른다(응답 일관성 시험용).
- `send_failures`: 승인 발송에 넣는 Gmail 고의 실패(차례로 한 번씩).
"""

from dataclasses import dataclass, field

from google.genai.errors import ClientError

from app.clients.gmail import GoogleUnavailable

# 도구 이름(`app/tools/registry.py`)
DRAFT = "draft_replies"
EXTRACT = "extract_deal_terms"
CHECK = "check_required_fields"
FOLLOWUP = "draft_followup_replies"
QUOTE = "create_quote"
GENERAL_TOOLS = frozenset({DRAFT})
QUOTE_TOOLS = frozenset({EXTRACT, CHECK, QUOTE, DRAFT})
FOLLOWUP_TOOLS = frozenset({EXTRACT, CHECK, FOLLOWUP})


def gemini_rate_limit():
    """Gemini 한도 초과(429 RESOURCE_EXHAUSTED)와 같은 SDK 예외."""
    return ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "injected"}})


def gmail_unavailable():
    """Gmail 발송 5xx(실제로 나갔는지 모르는 실패)."""
    return GoogleUnavailable("HTTP 503")


@dataclass(frozen=True)
class Expect:
    end_reason: str
    kind: str                                  # 후보 종류: general/followup/quote
    tools: frozenset                           # 정답 도구 조합(이 실행에서 부른 도구 집합)
    candidates: tuple[int, int] = (2, 3)       # 후보 개수 범위
    needs_review: bool = False
    notice: str | None = None
    asks: tuple[str, ...] = ()                 # 모든 재질문 후보가 묻는 항목
    quote: bool = False                        # 이 실행의 견적서 초안이 저장됨
    forbidden: tuple[str, ...] = ()            # 어느 후보 본문에도 없어야 하는 표현(원문에 없는 값)
    approval: tuple[str, ...] = ()             # 승인 발송을 차례로 했을 때의 결과 키(`ApprovalResult.outcome`)


@dataclass(frozen=True)
class Scenario:
    key: str
    category: str                              # 정상 / 정보 부족 / 도구 실패 / 판단 오류
    title: str
    subject: str
    body: str
    expect: Expect
    sender: str = "buyer@example.invalid"
    inject: dict = field(default_factory=dict)
    fake: dict | list = field(default_factory=dict)
    send_failures: tuple = ()

    @property
    def needs_access(self) -> bool:
        """승인 발송 단계가 있어 Gmail 연결(GoogleAccess)이 필요한가."""
        return bool(self.expect.approval)


# --- 가짜 LLM 응답(시험 메일에 맞춘 지어낸 값) -----------------------------------------------------
GENERAL = {"intent": "general", "reason": "제품 자료를 묻는 일반 문의"}
DEAL = {"intent": "deal", "reason": "수량과 납기가 있는 견적 요청"}
CLEAN = {"candidates": [
    {"label": "간단 안내", "body": "문의 감사합니다. 제품 안내 자료를 정리해 다시 연락드리겠습니다."},
    {"label": "자세한 안내", "body": "관심 가져 주셔서 감사합니다. 담당자가 확인한 뒤 자료와 함께 회신드리겠습니다."},
]}
INVENTED = {"candidates": [
    {"label": "간단 안내", "body": "총 500만원에 11월 30일까지 공급해 드릴 수 있습니다."},
    {"label": "자세한 안내", "body": "확인 뒤 다시 안내드리겠습니다."},
]}
QUOTE_REPLY = {"candidates": [
    {"label": "간단 안내", "body": "요청하신 견적서를 첨부드립니다. 확인 부탁드립니다."},
    {"label": "상세 안내", "body": "문의 감사합니다. 요청하신 품목의 견적서를 첨부했으니 검토 부탁드립니다."},
]}
FOLLOWUP_REPLY = {"candidates": [
    {"label": "짧게", "body": "희망 납기를 알려 주시면 바로 견적을 드리겠습니다."},
    {"label": "자세히", "body": "견적 준비를 위해 납기(받으실 날짜)를 알려 주세요."},
]}
TERMS = {
    "customer_name": "가상상사", "due_date": "2026-11-20",
    "items": [{"item_name": "가상 복사용지", "quantity": 100, "unit": "박스", "unit_price": None}],
    "contact_name": None, "contact_phone": None, "delivery_place": None, "note": None,
    "evidence": [{"field": "quantity", "excerpt": "100박스"}, {"field": "due_date", "excerpt": "11월 20일"}],
}
NO_DUE = {**TERMS, "due_date": None, "evidence": [{"field": "quantity", "excerpt": "100박스"}]}
FIX = {"cause": "앞 단계 결과가 메일 내용과 맞지 않음", "feedback": "메일 원문과 거래 항목에 있는 값만 쓰세요"}

GENERAL_BODY = "안녕하세요, 가상오피스입니다. 사무용품 제품 안내 자료를 받아 볼 수 있을까요?"
DEAL_BODY = "가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다. 11월 20일까지 필요합니다."
NO_DUE_BODY = "가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다."

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "normal_general", "정상", "일반 문의 → 답장 후보", "제품 안내 자료 문의", GENERAL_BODY,
        Expect("awaiting_approval", "general", GENERAL_TOOLS),
        fake={"EmailAnalysis": [GENERAL], "DraftOutput": [CLEAN]},
    ),
    Scenario(
        "normal_quote", "정상", "필수 항목을 다 갖춘 거래 → 견적서", "복사용지 견적 요청", DEAL_BODY,
        Expect("awaiting_approval", "quote", QUOTE_TOOLS, quote=True),
        fake={"EmailAnalysis": [DEAL], "ExtractedDealTerms": [TERMS], "DraftOutput": [QUOTE_REPLY]},
    ),
    Scenario(
        "missing_info", "정보 부족", "납기가 빠진 거래 → 재질문", "복사용지 견적 요청", NO_DUE_BODY,
        Expect("followup_question", "followup", FOLLOWUP_TOOLS, asks=("due_date",)),
        fake={"EmailAnalysis": [DEAL], "ExtractedDealTerms": [NO_DUE], "FollowupDraft": [FOLLOWUP_REPLY]},
    ),
    Scenario(
        "gmail_error", "도구 실패", "승인 발송 중 Gmail 5xx → 실패 안내 → 다시 승인", "제품 안내 자료 문의",
        GENERAL_BODY,
        Expect("awaiting_approval", "general", GENERAL_TOOLS, approval=("failed_unknown", "sent")),
        sender="gmail-case@example.invalid",
        fake={"EmailAnalysis": [GENERAL], "DraftOutput": [CLEAN]},
        send_failures=(gmail_unavailable,),
    ),
    Scenario(
        "gemini_rate_limit", "도구 실패", "답장 후보 중 Gemini 한도 → 기본 답장 틀·확인 필요", "제품 안내 자료 문의",
        GENERAL_BODY,
        Expect("awaiting_approval", "general", GENERAL_TOOLS, candidates=(1, 1), needs_review=True,
               notice="rate_limit"),
        inject={"DraftOutput": [gemini_rate_limit]},
        fake={"EmailAnalysis": [GENERAL]},
    ),
    Scenario(
        "wrong_tool", "판단 오류", "거래 메일을 일반 문의로 잘못 분류 → 성찰이 거래 경로로 고침", "복사용지 견적 요청",
        DEAL_BODY,
        Expect("awaiting_approval", "quote", QUOTE_TOOLS, quote=True),
        inject={"EmailAnalysis": [GENERAL]},
        fake={"DraftOutput": [CLEAN, QUOTE_REPLY], "ReflectAnalysis": [FIX], "ExtractedDealTerms": [TERMS]},
    ),
    Scenario(
        "hallucination", "판단 오류", "원문에 없는 금액·날짜를 지어낸 후보 → 성찰이 다시 씀", "제품 안내 자료 문의",
        GENERAL_BODY,
        Expect("awaiting_approval", "general", GENERAL_TOOLS, forbidden=("500만원", "11월 30일")),
        inject={"DraftOutput": [INVENTED]},
        fake={"EmailAnalysis": [GENERAL], "DraftOutput": [CLEAN], "ReflectAnalysis": [FIX]},
    ),
)
SCENARIOS_BY_KEY = {s.key: s for s in SCENARIOS}
