"""필수 항목 출처(계약 5절). 무역서류 문서 종류별 목록은 계약 15.3절(kekorea-port 2절 이식).

무역 필수 키는 원본 reference/kekorea/Quotation_KEKOREA/agent/review_fields.py의
문서 종류별 필수 항목에서 상대방에게 재질문할 항목만 담는다[임시: 협의 13-사용].
문서번호·단가·발행 회사 정보는 재질문 목록에서 빼고 문서 생성 도구의 blocking_issues로
다룬다(계약 15.3절). RAG 근거 표시(gmail-quote-mvp 22)는 아직 범위 밖이라 source="config"다.
"""

from copy import deepcopy

from app.config import DEFAULT_REQUIRED_FIELDS
from app.graph.state import RequiredFields

FIELD_LABELS = {field["key"]: field["label"] for field in DEFAULT_REQUIRED_FIELDS}
FIELD_LABELS.update({
    "incoterms": "인코텀즈(인도조건·지정장소)",
    "payment_terms": "결제조건",
    "currency": "통화",
    "counterparty_legal_name": "상대방 법인명",
    "counterparty_address": "상대방 주소",
    "item_name": "품목명",
    "unit": "수량 단위",
    "quantity": "수량",
    "discount_percent": "할인율",
    "country_of_origin": "원산지",
    "shipment_reference": "선적번호",
    "container_count": "컨테이너 수",
})

# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py missing_review_fields의
# 문서 종류별 조건을 계약 15.3절 키로 옮긴 목록(PL은 통화·단가·할인을 요구하지 않는다).
TRADE_REQUIRED_FIELDS = {
    "PI": ["incoterms", "payment_terms", "currency", "counterparty_legal_name",
           "counterparty_address", "item_name", "unit", "quantity", "discount_percent"],
    "PO": ["incoterms", "payment_terms", "currency", "counterparty_legal_name",
           "counterparty_address", "item_name", "unit", "quantity"],
    "CI": ["incoterms", "currency", "country_of_origin", "shipment_reference",
           "counterparty_legal_name", "counterparty_address", "item_name", "unit",
           "quantity", "discount_percent"],
    "PL": ["incoterms", "shipment_reference", "container_count", "counterparty_legal_name",
           "counterparty_address", "item_name", "unit", "quantity"],
}


def get_required_fields(user_id: int, doc_kind: str = "quote") -> RequiredFields:
    if doc_kind in TRADE_REQUIRED_FIELDS:
        fields = [{"key": key, "label": FIELD_LABELS[key]} for key in TRADE_REQUIRED_FIELDS[doc_kind]]
    else:
        fields = deepcopy(DEFAULT_REQUIRED_FIELDS)
    return {"fields": fields, "source": "config", "evidence": []}
