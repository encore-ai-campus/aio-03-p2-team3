"""kekorea-port 2절(A 묶음): 무역서류 추출·후처리 이식 테스트. 가짜 LLM만 쓴다.

- 원본 test_extractor.py의 근거 확인 검사(verify_item_quotes)를 pytest로 옮긴다.
- 같은 입력에 사본(reference/kekorea) 함수와 이식본 함수의 후처리 결과가 같은지 비교한다.
  사본 불러오기는 이식 규칙이 허용하는 임시 읽기(sys.modules 조작)이고 사본은 고치지 않는다.
- 회사 고유 값은 쓰지 않는다(가상 거래처 Acme Trading, 가상 상품 Virtual Serum).
"""

import copy
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from app.graph.build import build_graph
from app.graph.run import start_run
from app.llm import client
from app.quote.required_fields import FIELD_LABELS, TRADE_REQUIRED_FIELDS, get_required_fields
from app.tools.check_required_fields import find_missing
from app.tools.extract_deal_terms import (
    ExtractedTradeCIDoc,
    ExtractedTradeDoc,
    ExtractedTradeItem,
    postprocess_trade_draft,
)
from app.tools.registry import TOOLS
from app.trade.common import postprocess
from app.trade.common.trade_documents import current_issue_date
from app.trade.common.verify_quotes import verify_item_quotes
from tests.fakes.llm import FakeLLM

REPOSITORY = Path(__file__).resolve().parents[1]
REFERENCE = REPOSITORY / "reference" / "kekorea"
AGENT_PACKAGE = "Quotation_KEKOREA.agent"

# 검사 대상 함수가 쓰지 않는 의존만 가짜로 채운다(사본 app_postprocess의 맨 위 import용).
STUB_ATTRIBUTES = {
    "counterparties": ("load_company_profiles", "apply_company_profiles"),
    "promotions": ("apply_promotion_commands", "recalculate_order_promotions"),
    "samples": ("ensure_sample_rows", "edit_sample_rows", "is_manual_sample"),
    "attachments": ("prepare_uploads", "input_blocks"),
    "branding": ("resolve_company_seal",),
    "seal_storage": ("download_company_seal",),
    "pricing": ("is_eclado_supplier", "load_local_seed", "load_supabase_catalog", "match_eclado_product"),
    "ci_import": ("prepare_ci_import", "is_pi_import", "ci_import_issues", "ci_render_data",
                  "is_ci_conversion_request", "apply_document_prices"),
    "packing_review": ("reconcile_packing", "normalize_packing_inputs", "packing_total_changes",
                       "apply_approved_packing_totals", "PACKING_SOURCE_FIELDS"),
    "renderers": ("format_currency_amount", "render_files"),
    "review_fields": ("missing_review_fields", "apply_review_value"),
}


def _load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reference():
    """사본의 app_postprocess·extractor·trade_documents를 읽기 전용으로 불러온다.

    app_postprocess는 PyMuPDF(attachments) 등 이식 범위 밖 의존을 맨 위에서 import하므로
    검사 대상 함수가 쓰지 않는 의존만 가짜 모듈로 채운다. 결과 비교에 필요한
    trade_documents(표준 라이브러리만 쓴다)는 실제 사본을 불러 온다.
    """
    added = []
    sys.modules["Quotation_KEKOREA"] = types.ModuleType("Quotation_KEKOREA")
    sys.modules[AGENT_PACKAGE] = types.ModuleType(AGENT_PACKAGE)
    added += ["Quotation_KEKOREA", AGENT_PACKAGE]
    trade_documents = _load_source(
        AGENT_PACKAGE + ".trade_documents", REFERENCE / "Quotation_KEKOREA/agent/trade_documents.py")
    added.append(AGENT_PACKAGE + ".trade_documents")
    for module_name, attributes in STUB_ATTRIBUTES.items():
        stub = types.ModuleType(AGENT_PACKAGE + "." + module_name)

        def forbidden(*args, **kwargs):
            pytest.fail("동일성 검사 대상 함수가 이 의존을 부르면 안 된다")

        for attribute in attributes:
            setattr(stub, attribute, forbidden)
        sys.modules[AGENT_PACKAGE + "." + module_name] = stub
        added.append(AGENT_PACKAGE + "." + module_name)
    extractor = _load_source(AGENT_PACKAGE + ".extractor", REFERENCE / "Quotation_KEKOREA/agent/extractor.py")
    added.append(AGENT_PACKAGE + ".extractor")
    try:
        postprocess_source = _load_source(
            "reference_kekorea_app_postprocess", REFERENCE / "Quotation_KEKOREA/app_postprocess.py")
        added.append("reference_kekorea_app_postprocess")
        yield types.SimpleNamespace(
            postprocess=postprocess_source, extractor=extractor, trade_documents=trade_documents)
    finally:
        for name in added:
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 API 호출"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


# ── 사본·이식본 후처리 동일성(kekorea-port 2절 완료 기준: 개별 후처리 함수) ──────────

DISCOUNT_PROMPTS = [
    "Please apply a 10% discount on this order.",
    "10% 할인율 적용하지마",
    "Please sell at list price for this order.",
    "할인 없이 진행해 주세요.",
    "We want a discount but did not decide the rate.",
    "First apply 5% then change to 10% discount.",
    "5% discount for item A and 10% discount for item B.",
    "no special price condition",
    "do not apply the 10% discount rate",
    "2+1 행사로 진행하고 할인율은 적용하지 마세요.",
]


@pytest.mark.parametrize("prompt", DISCOUNT_PROMPTS)
def test_discount_instruction_matches_reference(reference, prompt):
    assert postprocess.discount_instruction(prompt) == reference.postprocess._discount_instruction(prompt)


REMARK_PROMPTS = [
    "Remarks: handle with care",
    "NOTE: fragile, keep dry",
    "SPECIAL INSTRUCTIONS: ship ASAP",
    "ADDITIONAL TERMS: subject to contract",
    "no remark section here",
    "Remarks:",
    "Remarks: handle with care. Buyer: Acme Trading",
]


@pytest.mark.parametrize("prompt", REMARK_PROMPTS)
def test_explicit_remark_matches_reference(reference, prompt):
    assert postprocess.explicit_remark(prompt) == reference.postprocess._explicit_remark(prompt)


SHIP_TO_PROMPTS = [
    "Ship To: 1 Fiction Ave",
    "SHIP TO - PARTY: Acme Trading",
    "배송지: 서울 강남",
    "deliver to our warehouse",
    "CONSIGNEE ADDRESS: 2 Made-up Street",
    "destination port: Busan",
    "alamat pengiriman: Jakarta",
    "no destination stated",
    "FOB Busan",
]


@pytest.mark.parametrize("prompt", SHIP_TO_PROMPTS)
def test_has_explicit_ship_to_matches_reference(reference, prompt):
    assert postprocess.has_explicit_ship_to(prompt) == reference.postprocess._has_explicit_ship_to(prompt)


DOC_KIND_PROMPTS = [
    "PI 작성 요청",
    "Please create a PI",
    "Please prepare a pro forma invoice for order 1",
    "발주서 만들어 주세요",
    "create a packing list",
    "상업송장 발행 부탁드립니다",
    "we attached our PO for reference",
    "견적 문의드립니다",
    "PO 받았습니다. 검토하겠습니다.",
    "",
]


@pytest.mark.parametrize("prompt", DOC_KIND_PROMPTS)
def test_recognize_doc_kind_matches_reference(reference, prompt):
    assert postprocess.recognize_doc_kind(prompt) == reference.postprocess._requested_document_type(prompt)


@pytest.mark.parametrize("value", ["100", "1000.50", "1,000.000", "0", None, "", "abc"])
def test_format_quantity_display_matches_reference(reference, value):
    assert postprocess.format_quantity_display(value) == reference.postprocess._format_quantity_display(value)


CURRENCY_CASES = [
    ({"currency": None}, "price is $ 8.00 per pcs"),
    ({"currency": None}, "USD 8.00 per pcs"),
    ({"currency": None}, "₩8,000 원화"),
    ({"currency": None}, "EUR 10 and USD 5 are both mentioned"),
    ({"currency": "KRW"}, "unit price is USD 10"),
    ({"currency": None}, "no money mentioned at all"),
    ({"currency": "USD"}, "USD 8.00"),
]


@pytest.mark.parametrize("draft, prompt", CURRENCY_CASES)
def test_normalize_currency_alias_matches_reference(reference, draft, prompt):
    mine, theirs = copy.deepcopy(draft), copy.deepcopy(draft)
    postprocess.normalize_currency_alias(mine, prompt)
    reference.postprocess._normalize_currency_alias(theirs, prompt)
    assert mine == theirs


QUANTITY_ALIAS_CASES = [
    ({"items": [{"source": "Quantity: 100 PCS", "quantity": None, "paid_quantity": None,
                 "unit": None, "price_basis": None}]}, "Quantity: 100 PCS"),
    ({"items": [{"source": "ordered qty: 5 CTNS", "quantity": None, "paid_quantity": None,
                 "unit": None, "price_basis": "USD/KG"}]}, "ordered qty: 5 CTNS"),
    ({"items": [{"source": "Volume: 32,000 KG", "quantity": None, "paid_quantity": None,
                 "unit": None, "price_basis": None}]}, "Volume: 32,000 KG"),
    ({"items": [{"source": "soap order", "quantity": "10", "paid_quantity": "10",
                 "unit": "BOX", "price_basis": None}]}, "Quantity: 7 SET"),
    ({"items": [{"source": None, "quantity": None, "paid_quantity": None,
                 "unit": None, "price_basis": None}]}, "qty: 3 DRUMS"),
    ({"items": [{"source": "first qty 2 BOX and more qty 5 BOX", "quantity": None,
                 "paid_quantity": None, "unit": None, "price_basis": None}]}, "same text"),
]


@pytest.mark.parametrize("draft, prompt", QUANTITY_ALIAS_CASES)
def test_normalize_quantity_aliases_matches_reference(reference, draft, prompt):
    mine, theirs = copy.deepcopy(draft), copy.deepcopy(draft)
    postprocess.normalize_quantity_aliases(mine, prompt)
    reference.postprocess._normalize_quantity_aliases(theirs, prompt)
    assert mine == theirs


SYNCHRONIZE_CASES = [
    {"product_family": "cosmetics", "items": [
        {"quantity": "10", "promotion": "2+1", "free_quantity": None, "unit": None}]},
    {"product_family": "cosmetics", "items": [{"quantity": "0", "unit": None}]},  # 명시적 수량 0 보존
    {"product_family": None, "items": [
        {"quantity": None, "paid_quantity": "6", "promotion": "3+1"}]},
    {"product_family": None, "items": [{"quantity": None, "paid_quantity": None}]},
    {"product_family": None, "items": [{"quantity": "5", "promotion": "not-a-rule"}]},
    {"product_family": None, "items": []},
]


@pytest.mark.parametrize("draft", SYNCHRONIZE_CASES)
def test_synchronize_quantities_matches_reference(reference, draft):
    mine, theirs = copy.deepcopy(draft), copy.deepcopy(draft)
    postprocess.synchronize_quantities(mine)
    reference.postprocess._synchronize_extracted_quantities(theirs)
    assert mine == theirs


KEEP_DELIVERY_CASES = [
    ({"incoterms": "FOB Busan"}, "ship before June 5"),
    ({"incoterms": "FOB Busan"}, "delivery deadline May 5"),
    ({"incoterms": None}, "Shipment deadline: May 5"),
    ({"incoterms": "FOB Busan"}, "payment in advance"),
    ({"incoterms": "FOB Busan"}, None),
]


@pytest.mark.parametrize("draft, note", KEEP_DELIVERY_CASES)
def test_keep_delivery_note_matches_reference(reference, draft, note):
    mine, theirs = copy.deepcopy(draft), copy.deepcopy(draft)
    postprocess.keep_delivery_note_in_terms(mine, note)
    reference.postprocess._keep_delivery_note_in_terms(theirs, note)
    assert mine == theirs


def test_apply_issuer_defaults_fills_empty_fields_from_user_settings():
    """원본 _apply_ke_korea_company_defaults의 고정값 대신 사용자별 설정으로 바꾼 동작."""
    draft = {"seller": {"legal_name": "  ", "address": None}, "buyer": {"legal_name": "Acme Trading"}}
    company = {"legal_name_en": "Fiction Export Co. LTD", "address": "2 Made-up Street",
               "contact": "Sales team", "phone": "", "email": None}
    result = postprocess.apply_issuer_defaults(draft, "PI", company)
    assert result["seller"]["legal_name"] == "Fiction Export Co. LTD"
    assert result["seller"]["address"] == "2 Made-up Street"
    assert result["seller"]["contact"] == "Sales team"
    assert result["seller"].get("phone") is None and result["seller"].get("email") is None
    assert result["buyer"] == {"legal_name": "Acme Trading"}  # 상대방 역할은 건드리지 않는다

    empty = postprocess.apply_issuer_defaults({"seller": {}}, "PO", None)
    assert empty["seller"] == {} and empty["buyer"] == {}  # 설정이 없으면 채우지 않는다


# ── 근거 확인 검사(원본 test_extractor.py 이식) ──────────────────────────────

VERIFY_CASES = [
    # 원본 test_extractor.py test_verified_translations_are_not_rejected_as_nonverbatim
    ({"buyer": {"legal_name": "华星贸易有限公司 (Huaxing Trading Co., Ltd.)",
                "address": "上海市浦东新区 (Pudong New Area, Shanghai)"},
      "items": [{"product_name": "Solar Cell", "capacity": None, "quantity": "20",
                 "unit_price": None, "source": "Mohon kirim Solar Cell 20 pcs."}],
      "source_notes": ["买方：华星贸易有限公司，地址：上海市浦东新区。Mohon kirim Solar Cell 20 pcs."],
      "conflicts": []},
     "买方：华星贸易有限公司，地址：上海市浦东新区。Mohon kirim Solar Cell 20 pcs."),
    # 원본 test_extractor.py test_source_notes_must_be_verbatim_evidence
    ({"items": [], "source_notes": ["invented source"], "conflicts": []}, "Buyer asks for PI"),
    # 원본 test_extractor.py test_quote_guard_blocks_invented_item_amount
    ({"items": [{"product_name": "Solar Cell", "capacity": None,
                 "source": "Solar Cell 10 PCS USD 5.00", "quantity": "10", "unit_price": "50.00"}],
      "conflicts": []},
     "Solar Cell 10 PCS USD 5.00 FOB Busan"),
    # 원본 test_extractor.py test_quote_guard_flags_missing_company_address
    ({"items": [], "buyer": {"legal_name": "Buyer Ltd", "address": "55 Fiction Ave"}}, "Buyer Ltd placed an order"),
    ({"items": [{"product_name": "Cream", "source": "Cream qty 3 PCS", "quantity": "3",
                 "free_quantity": "0"}], "conflicts": []}, "Cream qty 3 PCS"),
    ({"currency": "EUR", "items": [], "conflicts": []}, "price is 10 dollars"),
]


@pytest.mark.parametrize("draft, prompt", VERIFY_CASES)
def test_verify_item_quotes_matches_reference(reference, draft, prompt):
    mine, theirs = copy.deepcopy(draft), copy.deepcopy(draft)
    assert verify_item_quotes(mine, prompt) == reference.extractor.verify_item_quotes(theirs, prompt)


def test_verified_translations_are_not_rejected_as_nonverbatim():
    source = "买方：华星贸易有限公司，地址：上海市浦东新区。Mohon kirim Solar Cell 20 pcs."
    draft = {
        "buyer": {"legal_name": "华星贸易有限公司 (Huaxing Trading Co., Ltd.)",
                  "address": "上海市浦东新区 (Pudong New Area, Shanghai)"},
        "items": [{"product_name": "Solar Cell", "capacity": None,
                   "quantity": "20", "unit_price": None,
                   "source": "Mohon kirim Solar Cell 20 pcs."}],
        "source_notes": [source], "conflicts": []}
    assert verify_item_quotes(draft, source)["conflicts"] == []


def test_source_notes_must_be_verbatim_evidence():
    draft = {"items": [], "source_notes": ["invented source"], "conflicts": []}
    result = verify_item_quotes(draft, "Buyer asks for PI")
    assert any("source note" in issue.lower() for issue in result["conflicts"])


def test_quote_guard_blocks_invented_item_amount():
    draft = {"items": [{"product_name": "Solar Cell", "capacity": None,
                        "source": "Solar Cell 10 PCS USD 5.00",
                        "quantity": "10", "unit_price": "50.00"}], "conflicts": []}
    result = verify_item_quotes(draft, "Solar Cell 10 PCS USD 5.00 FOB Busan")
    assert any("unit price" in issue for issue in result["conflicts"])


def test_quote_guard_flags_missing_company_address():
    draft = {"items": [], "buyer": {"legal_name": "Buyer Ltd", "address": "55 Fiction Ave"}}
    result = verify_item_quotes(draft, "Buyer Ltd placed an order")
    assert any("Buyer address" in issue for issue in result["conflicts"])


# ── 프롬프트 지시 규칙(원본 SYSTEM_PROMPT 이식, 회사 고유 값 제외) ────────────────

def test_extract_trade_terms_prompt_keeps_instruction_rules():
    from app.prompts.extract_trade_terms import TEMPLATE

    # 발행일을 원문에서 복사하지 않음
    assert "do not copy a date from an order or email as the issue date" in TEMPLATE
    # 없는 값을 지어내지 않음
    assert "Never invent company names" in TEMPLATE
    # SHIP TO는 명시 라벨만
    assert "Never infer ship_to from the buyer address" in TEMPLATE
    # 통화 기호·ISO 코드
    assert "only a three-letter ISO code" in TEMPLATE
    # 다국어 입력·영문 출력(중국어 회사명·주소는 병기)
    assert "Chinese" in TEMPLATE and "(English translation)" in TEMPLATE and "Indonesian" in TEMPLATE
    # 프로모션 N+M
    assert '"Buy 3, get 1 free" to "3+1"' in TEMPLATE
    # 원본의 발행 회사·거래처 이름은 없다(회사 고유 값 금지)
    assert "KE KOREA" not in TEMPLATE and "KE Korea" not in TEMPLATE
    assert "ECLADO" not in TEMPLATE


def test_trade_schema_keeps_product_code_separate_and_ci_extension_keys():
    fields = ExtractedTradeItem.model_fields
    assert "product_code" in fields and "product_name" in fields
    assert "source_line_total" not in fields  # CI 확장 키는 CI 스키마에만
    assert "source_document_type" not in ExtractedTradeDoc.model_fields
    ci_fields = ExtractedTradeCIDoc.model_fields
    assert "source_document_type" in ci_fields and "source_total" in ci_fields


# ── 도구: 가짜 LLM으로 무역 경로·국내 경로 ────────────────────────────────────

PI_BODY = ("Hello, this is Acme Trading. Please create a PI for Virtual Serum 100 PCS "
           "at USD 8.00 per PCS. Incoterms FOB Busan, payment T/T. Remarks: handle with care.")

PI_RESPONSE = {
    "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
    "buyer": {"legal_name": "Acme Trading", "address": None, "contact": None,
              "phone": None, "email": None, "registration_details": None},
    "seller": {"legal_name": None, "address": None, "contact": None,
               "phone": None, "email": None, "registration_details": None},
    "items": [{
        "product_name": "Virtual Serum", "product_code": None, "capacity": "50ml",
        "quantity": "100", "unit": "PCS", "unit_price": "8.00", "price_basis": "USD/PCS",
        "discount_percent": None, "paid_quantity": "100", "free_quantity": None,
        "shipped_quantity": None, "promotion": None, "price_source": None,
        "source": "Virtual Serum 100 PCS at USD 8.00 per PCS", "package_type": None,
        "package_count": None, "net_weight_kg": None, "gross_weight_kg": None,
        "volume_cbm": None, "hs_code": None,
    }],
    "incoterms": "FOB Busan", "payment_terms": "T/T", "remarks": None,
    "document_number": None, "issue_date": None, "ship_to": None, "ship_to_source": None,
    "bill_to": None, "shipment_reference": None, "country_of_origin": None, "hs_code": None,
    "actual_package_count": None, "container_count": None,
    "declared_total_quantity": None, "declared_total_quantity_unit": None,
    "declared_net_weight_kg": None, "declared_gross_weight_kg": None, "declared_volume_cbm": None,
    "packages": [], "missing_fields": ["Buyer full legal name and address"],
    "conflicts": [], "source_notes": ["Virtual Serum 100 PCS at USD 8.00 per PCS", "FOB Busan"],
}

# CI 인식은 원본 _requested_document_type 규칙을 그대로 쓴다(계약 15.1절): PI 별칭이 작성
# 동사 근처(앞 45·뒤 25자)에 있으면 PI가 먼저 매칭되므로, 인용 PI는 명령어와 멀리 둔다.
CI_SUBJECT = "CI 작성 요청"
CI_BODY = ("Shipment S-1 cleared customs. Quoted from the received document: "
           "PI No. V-100, Virtual Serum 100 PCS at USD 8.00 per PCS, total USD 800.00.")

CI_RESPONSE = {
    **{key: value for key, value in PI_RESPONSE.items()
       if key not in ("items", "missing_fields", "source_notes")},
    "source_document_type": "PI", "source_total": "800.00",
    "items": [{**PI_RESPONSE["items"][0], "source_line_total": "800.00"}],
    "missing_fields": [], "conflicts": [],
    "source_notes": ["Virtual Serum 100 PCS at USD 8.00 per PCS"],
}

QUOTE_RESPONSE = {
    "customer_name": "가상상사",
    "items": [{"item_name": "가상 복사용지", "quantity": 100, "unit": "박스", "unit_price": None}],
    "due_date": "2026-11-20", "contact_name": None, "contact_phone": None,
    "delivery_place": None, "note": None,
    "evidence": [{"field": "customer_name", "excerpt": "가상상사"},
                 {"field": "quantity", "excerpt": "100박스"}],
}

FOLLOWUP = {"candidates": [
    {"label": "간단히 묻기", "subject": "Re: PI 작성 요청", "body": "회사 주소를 알려 주시겠어요?"},
    {"label": "목록으로 묻기", "subject": "", "body": "아래 항목을 알려 주세요.\n- 상대방 주소"},
]}


def trade_email(subject, body):
    return {
        "gmail_message_id": "fake-message", "thread_id": "fake-thread", "rfc_message_id": None,
        "from_addr": "buyer@example.invalid", "from_name": None,
        "to_addrs": ["demo@example.invalid"], "subject": subject, "body_text": body,
        "received_at": "2026-11-09T00:00:00+00:00", "direction": "in",
    }


def test_extract_deal_terms_trade_pi_path_with_fake_llm():
    fake = FakeLLM([PI_RESPONSE])
    with client.use_backend(fake):
        result = TOOLS["extract_deal_terms"].invoke({
            "email": trade_email("PI 작성 요청", PI_BODY), "user_id": 1})
    assert result.ok, result.error_message
    assert fake.schemas[0] is ExtractedTradeDoc  # CI가 아니면 CI 확장 키 스키마를 쓰지 않는다
    draft = result.value
    assert draft["doc_kind"] == "PI" and draft["document_type"] == "PI"
    assert draft["issue_date"] == current_issue_date()  # 발행일은 생성 시점 서울 날짜
    assert draft["remarks"] == "handle with care."      # 명시 라벨의 REMARK만(원본은 문장부호를 유지)
    assert draft["ship_to"] is None and "ship_to_source" not in draft  # 명시 라벨 없으면 SHIP TO 없음
    assert draft["conflicts"] == []                     # 근거가 모두 원문에 있다
    assert draft["missing_fields"] == ["Buyer full legal name and address"]
    item = draft["items"][0]
    assert item["quantity"] == "100" and item["paid_quantity"] == "100"
    assert item["free_quantity"] == "0" and item["shipped_quantity"] == "100"
    assert item["discount_percent"] == "0"  # 할인 언급이 없으면 정가(0%)
    assert draft["currency"] == "USD" and draft["incoterms"] == "FOB Busan"
    assert "Virtual Serum 100 PCS at USD 8.00 per PCS" in fake.calls[0]
    assert "The selected output document type is PI." in fake.calls[0]


def test_extract_deal_terms_ci_from_pi_quote_uses_ci_schema():
    fake = FakeLLM([CI_RESPONSE])
    with client.use_backend(fake):
        result = TOOLS["extract_deal_terms"].invoke({
            "email": trade_email(CI_SUBJECT, CI_BODY), "user_id": 1})
    assert result.ok, result.error_message
    assert fake.schemas[0] is ExtractedTradeCIDoc  # CI일 때만 CI 확장 키(계약 15.2절)
    assert "source_document_type" in fake.calls[0]  # CI 규칙 문단이 프롬프트에 끼워진다
    draft = result.value
    assert draft["doc_kind"] == "CI" and draft["_ci_from_pi"] is True
    assert draft["payment_terms"] == "N/A"  # 첨부 PI의 결제·계좌 정보는 CI로 넘기지 않는다
    item = draft["items"][0]
    assert item["price_source"] == "Attached PI transaction price; verify against source"
    assert item["discount_percent"] == "0"
    assert draft["source_total"] == "800.00"  # 인쇄된 총액을 재계산하지 않고 보존


def test_extract_deal_terms_quote_path_unchanged():
    fake = FakeLLM([QUOTE_RESPONSE])
    with client.use_backend(fake):
        result = TOOLS["extract_deal_terms"].invoke({
            "email": trade_email("가상 견적 문의", "가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다.")})
    assert result.ok, result.error_message
    terms = result.value
    assert terms["doc_kind"] == "quote"  # 국내 견적서 경로는 그대로(계약 15.2절)
    assert terms["customer_name"] == "가상상사"
    assert terms["evidence"] == {"customer_name": "가상상사", "quantity": "100박스"}


def test_extract_deal_terms_fills_counterparty_from_profiles():
    profiles = [{"company_key": "acme", "legal_name": "Acme Trading Co. Ltd.",
                 "aliases": ["Acme Trading"], "address": "1 Fiction Ave", "contact": None,
                 "phone": "+00-000-0000", "email": "sales@example.invalid",
                 "registration_details": None, "default_ship_to": "Fiction Warehouse",
                 "ship_to_phone": "+00-111-1111"}]
    with client.use_backend(FakeLLM([PI_RESPONSE])):
        result = TOOLS["extract_deal_terms"].invoke({
            "email": trade_email("PI 작성 요청", PI_BODY), "user_id": 1,
            "counterparties": profiles,
            "company": {"company_name": "Fiction Export Co. LTD", "contact": "Sales team"}})
    assert result.ok, result.error_message
    draft = result.value
    # 주문 값 우선, 빈 값만 채운다(원본 apply_company_profiles 동작).
    assert draft["buyer"]["legal_name"] == "Acme Trading Co. Ltd."  # 별칭 → 등록 법인명
    assert draft["buyer"]["address"] == "1 Fiction Ave"
    assert draft["buyer"]["phone"] == "+00-000-0000"
    # 등록된 기본 배송지·발행 회사 기본값(사용자별 설정)도 채운다.
    assert draft["ship_to"] == "Fiction Warehouse / Tel: +00-111-1111"
    assert draft["seller"]["legal_name"] == "Fiction Export Co. LTD"
    assert draft["seller"]["contact"] == "Sales team"


def test_postprocess_trade_draft_keeps_reference_order_for_quantities():
    """후처리 파이프라인이 원본 _extract_draft와 같은 순서로 수량·할인·발행사를 다룬다."""
    draft = ExtractedTradeDoc.model_validate(PI_RESPONSE).model_dump()
    result = postprocess_trade_draft(draft, "PI", f"PI 작성 요청\n{PI_BODY}", None, [])
    assert result["items"][0]["discount_percent"] == "0"
    assert result["seller"]["legal_name"] is None  # 설정이 없으면 발행사를 지어내지 않는다
    assert result["doc_kind"] == "PI"


# ── 필수 항목 목록(계약 15.3절) ────────────────────────────────────────────

def test_get_required_fields_by_doc_kind():
    for doc_kind, keys in TRADE_REQUIRED_FIELDS.items():
        fields = get_required_fields(1, doc_kind)
        assert [field["key"] for field in fields["fields"]] == keys
        assert fields["source"] == "config" and fields["evidence"] == []
        assert all(field["label"] == FIELD_LABELS[field["key"]] for field in fields["fields"])
    # 국내 견적서 경로는 그대로
    quote = get_required_fields(1)
    assert [field["key"] for field in quote["fields"]] == [
        "customer_name", "item_name", "quantity", "due_date"]


def test_find_missing_trade_party_roles_and_quantity_variants():
    def terms(doc_kind, **values):
        return {"doc_kind": doc_kind, **values}

    pi = terms("PI", buyer={"legal_name": "Acme Trading", "address": "1 Fiction Ave"},
               incoterms="FOB Busan", payment_terms="T/T", currency="USD",
               items=[{"product_name": "Virtual Serum", "quantity": "100", "unit": "PCS",
                       "discount_percent": "0"}])
    assert find_missing(pi, get_required_fields(1, "PI")) == []
    # PI는 buyer, PO는 seller의 법인명·주소를 본다(계약 15.3절).
    po = terms("PO", seller={"legal_name": "Acme Trading"}, buyer={"legal_name": "Us"},
               incoterms="FOB Busan", payment_terms="T/T", currency="KRW",
               items=[{"product_name": "Virtual Serum", "quantity": "100", "unit": "PCS"}])
    assert find_missing(po, get_required_fields(1, "PO")) == ["counterparty_address"]
    # quantity는 quantity·paid_quantity 중 하나라도 있으면 있다(PL은 shipped_quantity도).
    paid_only = terms("PL", shipment_reference="S-1", container_count="1", incoterms="FOB Busan",
                      buyer={"legal_name": "Acme", "address": "1 Fiction Ave"},
                      items=[{"product_name": "Virtual Serum", "paid_quantity": "10", "unit": "PCS"}])
    assert find_missing(paid_only, get_required_fields(1, "PL")) == []
    shipped_only = terms("PL", shipment_reference="S-1", container_count="1", incoterms="FOB Busan",
                         buyer={"legal_name": "Acme", "address": "1 Fiction Ave"},
                         items=[{"product_name": "Virtual Serum", "shipped_quantity": "10"}])
    assert find_missing(shipped_only, get_required_fields(1, "PL")) == ["unit"]
    # 할인율은 None이면 빠짐이고 "0"(할인 없음)은 있음이다(계약 15.3절).
    no_discount = terms("PI", buyer={"legal_name": "Acme", "address": "1 Fiction Ave"},
                        incoterms="FOB Busan", payment_terms="T/T", currency="USD",
                        items=[{"product_name": "Virtual Serum", "quantity": "100", "unit": "PCS"}])
    assert find_missing(no_discount, get_required_fields(1, "PI")) == ["discount_percent"]


# ── 그래프: 거래 메일이 무역 추출 경로로 흐르는지(노드 연결) ─────────────────────

def test_trade_email_flows_through_trade_extraction(database):
    nodes = {"analyze_email": lambda s: {"intent": "deal"},
             "draft_replies": lambda s: {}, "make_quote": lambda s: {}}
    fake = FakeLLM([PI_RESPONSE, FOLLOWUP])
    with client.use_backend(fake):
        result = start_run(user_id=1, email=trade_email("PI 작성 요청", PI_BODY), mode="test",
                           database=database, graph=build_graph(node_overrides=nodes))
    assert result["deal_terms"]["doc_kind"] == "PI"
    assert result["missing_fields"] == ["counterparty_address"]  # PI 필수 키 기준(계약 15.3절)
    assert [field["key"] for field in result["required_fields"]["fields"]] == TRADE_REQUIRED_FIELDS["PI"]
    assert result["end_reason"] == "followup_question"
    assert all(candidate["kind"] == "followup" for candidate in result["candidates"])
