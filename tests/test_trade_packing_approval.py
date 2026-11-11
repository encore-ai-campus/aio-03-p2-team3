"""PL 합계 승인 pytest(원본 tests/test_packing_approval.py 이식 + 백엔드 서비스 시험).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_packing_approval.py
- 순수 함수(normalize_packing_inputs·packing_total_changes·apply_approved_packing_totals·래퍼
  reconcile_packing) 시험은 원본 그대로 옮겼다(가상 발행 회사 이름만 바꿨다).
- 이어서 `app/services/trade_docs.py` 백엔드(제안 저장·승인·취소·수정 기록, 조건부 갱신으로 중복
  방지 — 계약 15.5절)를 DB로 시험한다. 원본 `apply_approved_packing_totals`의 ValueError는
  서비스에서 None 반환 규칙으로 바뀐 것만 원본과 다르다(계약 15.5절 (1)).
"""
import copy
import threading

import pytest

from app.db.models import TradeDocument
from app.services.trade_docs import (
    approve_packing_totals,
    cancel_packing_approval,
    finalize_draft,
    revise_trade_document,
    save_trade_document,
)
from app.trade.pl.packing_review import (
    apply_approved_packing_totals,
    normalize_packing_inputs,
    packing_total_changes,
    reconcile_packing,
)
from tests.test_trade_packing import packing_example

ISSUER_NAME = "Testworks Trading Co. Ltd"


def source_draft():
    draft = packing_example()
    draft["issuer"] = {"legal_name_en": ISSUER_NAME}
    return draft


# ── 원본 순수 함수 시험(test_packing_approval.py 이식) ───────────────────────────

def test_explicit_units_and_container_size_are_parsed_without_multiplying():
    source = packing_example()
    source['container_count'] = '5 x 40FT Containers'
    source['declared_total_quantity'] = '618400 pcs'
    source['declared_net_weight_kg'] = '10,354.56 kg'
    result = normalize_packing_inputs(source)
    assert result['container_count'] == '5'
    assert result['declared_total_quantity'] == '618400'
    assert result['declared_total_quantity_unit'] == 'PCS'
    assert result['declared_net_weight_kg'] == '10354.56'
    assert result['_packing_original_totals']['container_count'] == '5 x 40FT Containers'
    assert source['declared_total_quantity'] == '618400 pcs'
    assert reconcile_packing(result)['issues'] == []


def test_total_proposal_shows_mixed_units_and_preserves_source_until_approval():
    source = packing_example()
    original = copy.deepcopy(source)
    proposals = packing_total_changes(source)
    quantity = next(change for change in proposals if change['field'] == 'declared_total_quantity')
    assert '616001 PCS' in quantity['calculated']
    assert '2399.48 KG' in quantity['calculated']
    assert source == original
    approved = apply_approved_packing_totals(source)
    assert approved['declared_volume_cbm'] == '35.477'
    assert approved['declared_total_quantity'] == '616001'
    assert approved['declared_total_quantity_unit'] == 'PCS'
    assert approved['_packing_approved_quantities'] == {'PCS': '616001', 'KG': '2399.48'}
    assert approved['_packing_original_totals']['declared_total_quantity'] == '618400'
    assert approved['items'] == source['items']
    assert reconcile_packing(approved)['discrepancies'] == []
    assert source == original


def test_totals_approval_cannot_override_invalid_rows_or_container_counts():
    for field, value in (('gross_weight_kg', 'invalid'), ('gross_weight_kg', '1')):
        source = packing_example()
        source['items'][0][field] = value
        with pytest.raises(ValueError):
            apply_approved_packing_totals(source)
    source = packing_example()
    source['container_count'] = 'five containers'
    with pytest.raises(ValueError):
        apply_approved_packing_totals(source)


def test_quantity_unit_conflicts_are_not_silently_reinterpreted():
    source = packing_example()
    source['declared_total_quantity'] = '618400 kg'
    source['declared_total_quantity_unit'] = 'PCS'
    normalized = normalize_packing_inputs(source)
    assert reconcile_packing(normalized)['issues']
    with pytest.raises(ValueError):
        apply_approved_packing_totals(normalized)


# ── 백엔드 서비스 시험(제안 저장·승인·취소·수정 기록, 중복 방지) ────────────────────

def test_save_stores_packing_proposal_and_blocks_until_approved(database):
    draft = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    assert draft["doc_kind"] == "PL" and draft["doc_no"].startswith("PL-")
    totals = draft["packing_totals"]
    assert totals["approved"] is False
    assert totals["quantity_complete"] is True
    # 원본/계산 합계 차이 제안이 저장돼 있다(계약 15.5절 changes·discrepancies).
    assert {change["field"] for change in totals["changes"]} == {"declared_volume_cbm", "declared_total_quantity"}
    assert any("volume (CBM)" in d for d in totals["discrepancies"])
    assert any("quantity total" in d for d in totals["discrepancies"])
    assert draft["status"] == "needs_input"  # 차이가 남아 승인 전이다
    assert draft["packing_approval_log"] == []


def test_approve_applies_calculated_totals_and_records_once(database):
    draft = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    approved = approve_packing_totals(1, draft["trade_doc_id"], database=database)
    assert approved is not None
    assert approved["packing_totals"]["approved"] is True
    assert approved["declared_volume_cbm"] == "35.477"
    assert approved["declared_total_quantity"] == "616001"
    assert approved["status"] == "ready"  # 차이가 해소돼 재검증을 통과한다
    assert approved["_packing_original_totals"]["declared_total_quantity"] == "618400"  # 원본 합계 보존
    assert [entry["action"] for entry in approved["packing_approval_log"]] == ["approved"]
    # 다시 승인해도 다시 적용·기록하지 않는다(중복 방지).
    again = approve_packing_totals(1, draft["trade_doc_id"], database=database)
    assert again["packing_totals"]["approved"] is True
    assert [entry["action"] for entry in again["packing_approval_log"]] == ["approved"]


def test_approve_rejects_invalid_rows_and_incomplete_quantities(database):
    draft = source_draft()
    draft["items"][0]["gross_weight_kg"] = "1"  # 순중량 > 총중량: 승인으로 무시할 수 없는 오류
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=draft)
    assert approve_packing_totals(1, saved["trade_doc_id"], database=database) is None
    incomplete = source_draft()
    incomplete["items"][2]["unit"] = None  # 수량·단위가 미확정인 행(quantity_complete 거짓)
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=incomplete)
    assert saved["packing_totals"]["quantity_complete"] is False
    assert approve_packing_totals(1, saved["trade_doc_id"], database=database) is None
    with database.session() as session:
        row = session.get(TradeDocument, saved["trade_doc_id"])
        assert row.status == "needs_input"
        assert row.draft["packing_totals"]["approved"] is False  # 문서는 승인 전 그대로


def test_cancel_restores_source_totals_and_requires_reapproval(database):
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    trade_doc_id = saved["trade_doc_id"]
    approve_packing_totals(1, trade_doc_id, database=database)
    cancelled = cancel_packing_approval(1, trade_doc_id, database=database)
    assert cancelled["packing_totals"]["approved"] is False
    assert cancelled["declared_volume_cbm"] == "35.475"  # 원본 합계로 되돌아간다
    assert cancelled["declared_total_quantity"] == "618400"
    assert cancelled["status"] == "needs_input"  # 다시 승인 대상
    assert [entry["action"] for entry in cancelled["packing_approval_log"]] == ["approved", "cancelled"]
    # 승인 없는 취소는 그대로 둔다.
    assert cancel_packing_approval(1, trade_doc_id, database=database)["packing_totals"]["approved"] is False


def test_revise_fills_values_and_resets_packing_approval_when_totals_change(database):
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    trade_doc_id = saved["trade_doc_id"]
    approve_packing_totals(1, trade_doc_id, database=database)
    # 원본 합계를 고치면 승인을 다시 받는다(보존 동작).
    revised = revise_trade_document(1, trade_doc_id, {"declared_volume_cbm": "35.500"},
                                    database=database)
    assert revised["declared_volume_cbm"] == "35.500"
    assert revised["packing_totals"]["approved"] is False
    assert revised["status"] == "needs_input"
    assert revised["packing_approval_log"][-1]["action"] == "revised"
    assert revised["packing_approval_log"][-1]["fields"] == ["declared_volume_cbm"]
    # 포장과 무관한 값 보충은 승인을 유지한다.
    approve_packing_totals(1, trade_doc_id, database=database)
    revised = revise_trade_document(1, trade_doc_id, {"document_number": "PL-100"},
                                    database=database)
    assert revised["document_number"] == "PL-100"
    assert revised["packing_totals"]["approved"] is True
    assert revised["packing_approval_log"][-1]["fields"] == ["document_number"]


def test_revise_ignores_placeholder_values_and_returns_draft_unchanged(database):
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    revised = revise_trade_document(1, saved["trade_doc_id"], {"document_number": "  "},
                                    database=database)
    assert revised["document_number"] == "DRAFT"  # 빈 값은 그대로(빈 값 추측 금지)
    assert revised["packing_approval_log"] == []


def test_service_guards_other_users_docs_and_non_pl_and_missing(database):
    with database.session() as session:
        from app.db.models import User
        session.add(User(id=2, google_sub="fake-sub-2", email="demo2@example.invalid"))
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    # 다른 사용자 문서는 없는 것과 같다.
    assert approve_packing_totals(2, saved["trade_doc_id"], database=database) is None
    assert cancel_packing_approval(2, saved["trade_doc_id"], database=database) is None
    assert revise_trade_document(2, saved["trade_doc_id"], {"document_number": "X"}, database=database) is None
    assert approve_packing_totals(1, 9999, database=database) is None
    # PL이 아니면 합계 승인 대상이 아니다(CI 초안).
    ci = finalize_draft({**source_draft(), "document_type": "CI", "currency": "USD",
                         "payment_terms": "T/T", "country_of_origin": "KR"})
    saved_ci = save_trade_document(database, user_id=1, thread_id="t1", draft=ci)
    assert approve_packing_totals(1, saved_ci["trade_doc_id"], database=database) is None


def test_sent_documents_cannot_be_modified(database):
    from sqlalchemy import update

    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    trade_doc_id = saved["trade_doc_id"]
    with database.session() as session:
        session.execute(update(TradeDocument).where(TradeDocument.id == trade_doc_id)
                        .values(status="sent"))
    assert approve_packing_totals(1, trade_doc_id, database=database) is None
    assert cancel_packing_approval(1, trade_doc_id, database=database) is None
    assert revise_trade_document(1, trade_doc_id, {"document_number": "X"}, database=database) is None


def test_concurrent_approvals_are_applied_once(database):
    saved = save_trade_document(database, user_id=1, thread_id="t1", draft=source_draft())
    trade_doc_id = saved["trade_doc_id"]
    results, barrier = [], threading.Barrier(2)

    def approve():
        barrier.wait()
        results.append(approve_packing_totals(1, trade_doc_id, database=database))

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    approved = [result for result in results if result is not None]
    assert len(approved) == 2  # 둘 다 승인 결과를 받지만(멱등)
    log = approved[0]["packing_approval_log"]
    assert [entry["action"] for entry in log] == ["approved"]  # 기록은 한 번만
    with database.session() as session:
        row = session.get(TradeDocument, trade_doc_id)
        assert row.status == "ready"
        assert [entry["action"] for entry in row.draft["packing_approval_log"]] == ["approved"]
        assert row.draft["declared_total_quantity"] == "616001"
