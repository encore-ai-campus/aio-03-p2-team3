"""메일과 채팅의 공통 검색. 질의 생성과 증거 조회는 문서 인덱싱과 분리한다."""
import re
from collections.abc import Callable
from typing import Protocol
from unicodedata import normalize

from app.knowledge.ports import Embedder, Repository

# 한국어 업무 표현을 영어 계약서 검색에 자주 쓰이는 형태로 보완한다.
CONTRACT_TERMS = {
    "결제": "payment invoice", "대금": "payment price", "선금": "advance payment deposit",
    "잔금": "balance payment", "입금": "payment remittance", "납기": "delivery lead time",
    "늦": "delay late delivery", "선적": "shipment shipping", "운송": "shipping freight",
    "반품": "return refund", "환불": "refund reimbursement", "하자": "defect warranty",
    "보증": "warranty guarantee", "기밀": "confidentiality nondisclosure",
    "해지": "termination", "취소": "cancellation termination",
    "위약": "penalty liquidated damages", "손해": "damages liability",
    "불가항력": "force majeure", "분쟁": "dispute arbitration", "준거법": "governing law",
    "견적": "quotation price", "최소주문": "minimum order MOQ", "독점": "exclusivity exclusive",
    "자동갱신": "automatic renewal", "유효기간": "validity expiration term",
}
COMMON = frozenset("the and are with from that this for you your our have will what please can could would "
                   "subject regards dear hello thanks thank 문의 확인 요청 부탁 안내 계약 조건 어떻게 알려 주세요".split())


def search_terms(query: str) -> list[str]:
    words = re.findall(r"[^\W_]{2,}", query.casefold())
    return list(dict.fromkeys(word for word in words if word not in COMMON))[:16]


def expanded_query(query: str) -> str:
    compact = "".join(query.split())
    english = " ".join(value for korean, value in CONTRACT_TERMS.items() if korean in compact)
    return f"{english}\n{query}" if english else query


class SearchPlan(Protocol):
    korean: str
    english: str
    filename: str | None
    counterparty: str | None


def retrieve(repository: Repository, owner: int, *, query: str, get_embedder: Callable[[], Embedder],
             document_id: str | None = None, counterparty_ids: tuple[int, ...] | None = None,
             plan_query: Callable[[str], SearchPlan] | None = None,
             rerank: Callable[[str, list[dict]], list[str]] | None = None) -> list[dict]:
    query = normalize("NFKC", query).strip()[:1600]
    if not query:
        return []
    if plan_query is not None:
        plan = plan_query(query)
        variants = [plan.korean, plan.english]
        # 모델은 검색 범위를 좁힐 수만 있다. 메일의 거래처나 명시 문서의 범위를 바꾸지 않는다.
        if not document_id and plan.filename and plan.filename.casefold() in query.casefold():
            matches = repository.find_for_chat(owner, filename=plan.filename, document_id=None)
            if len(matches) == 1:
                document_id = matches[0]["document_id"]
        if plan.counterparty and plan.counterparty.casefold() in query.casefold():
            matched = tuple(row["id"] for row in repository.counterparties(owner)
                            if row["legal_name"].casefold() == plan.counterparty.casefold())
            if matched:
                counterparty_ids = tuple(item for item in matched
                                         if counterparty_ids is None or item in counterparty_ids)
    else:
        enriched = expanded_query(query)
        variants = [query, enriched] if enriched != query else [query]

    embedder = get_embedder()
    batch = embedder.embed_documents(variants)
    batch.validate_for(len(variants), embedder.profile)
    ranked: dict[str, tuple[float, dict]] = {}
    for text, vector in zip(variants, batch.vectors, strict=True):
        clauses = repository.search_clauses(owner, document_id=document_id, counterparty_ids=counterparty_ids,
            vector=vector, profile=embedder.profile, terms=search_terms(text), limit=10 if rerank else 2)
        for index, clause in enumerate(clauses):
            key = clause["clause_id"]
            score = ranked.get(key, (0.0, clause))[0] + 1 / (10 + index)
            ranked[key] = score, clause
    candidates = [clause for _, clause in sorted(ranked.values(), key=lambda item: -item[0])[:10]]
    if not candidates or rerank is None:
        return candidates[:2]
    by_id = {clause["clause_id"]: clause for clause in candidates}
    return [by_id[key] for key in dict.fromkeys(rerank(query, candidates)) if key in by_id][:3]
