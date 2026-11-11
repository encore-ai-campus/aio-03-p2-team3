"""무역서류 저장과 PL 합계 승인 백엔드(kekorea-port 5절 D, 계약 15.5·15.7절).

그래프 밖 서비스다(화면 없음). `app/services/approval.py`와 같은 방식으로 사용자별 잠금과
조건부 UPDATE로 같은 문서의 승인·수정이 겹치지 않게 한다.
- `save_trade_document`: 문서 초안을 검증·저장하며 PL은 원본/계산 합계 비교 제안
  (`packing_totals.changes`·`discrepancies`, 계약 15.5절 `PackingTotals`)을 함께 남긴다.
- `approve_packing_totals`: 계약 15.5절 순서대로 (1) 저장된 초안을 다시 확인해 검증 오류·수량
  불완전면 `None`(원본 `apply_approved_packing_totals`의 ValueError를 이 반환 규칙으로 바꾼다),
  (2) 승인 적용(원본 합계 보존, 계산 가능한 합계만 적용), (3) 재검증으로 status 재판정,
  (4) `packing_totals`을 `approved=True`로 다시 채워 저장한다. 이미 승인된 문서는 그 초안을
  그대로 돌려준다(중복 기록 없음).
- `cancel_packing_approval`: 승인 전의 원본 합계(`_packing_original_totals`)로 되돌리고 다시
  승인 대상(`needs_input`)으로 만든다.
- `revise_trade_document`: 빠진 값을 넣어 재검증·저장한다. 품목·원본 합계 값을 고치면 이미 난
  승인은 무효로 되돌린다(보존 동작: 품목/원본 합계 수정 후에는 다시 승인받는다).
- 승인·취소·수정 이력은 초안의 `packing_approval_log`(PL만)에 남긴다.
- 발행사 키 `issuer_key`는 초안의 발행 회사 스냅샷(`issuer`, 계약 15.7절: 설정 변경이 기존 문서를
  바꾸지 않는다)에서 정한다. `status="sent"`인 문서는 승인·취소·수정하지 않는다(승인 전 발송은
  불가하므로 sent는 확정 상태다).
"""
from copy import deepcopy
from decimal import Decimal
from threading import Lock
from weakref import WeakKeyDictionary

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import TradeDocument, User, utcnow
from app.trade.counterparties import name_key
from app.trade.packing_review import (
    PACKING_SOURCE_FIELDS,
    apply_approved_packing_totals,
    normalize_packing_inputs,
    packing_total_changes,
    reconcile_packing,
)
from app.trade.review_fields import ReviewField, apply_review_value, field_value
from app.trade.trade_documents import validate_and_calculate

DOC_KINDS = {"PI", "PO", "CI", "PL"}

_locks_guard = Lock()
_locks = WeakKeyDictionary()


def _user_lock(database, user_id: int) -> Lock:
    with _locks_guard:
        return _locks.setdefault(database, {}).setdefault(user_id, Lock())


def issuer_key_of(draft: dict) -> str:
    """발행 회사 스냅샷의 이름 키(계약 15.4절: legal_name_en → legal_name → company_name 정규화)."""
    issuer = draft.get("issuer") or {}
    name = str(issuer.get("legal_name_en") or issuer.get("legal_name")
               or issuer.get("company_name") or "").strip()
    return name_key(name)


def _packages_total(data: dict) -> dict:
    """packages 배열 net/gross 합계(원본 pi_pdf 폴백 식 그대로. 배열이 없으면 값 없음)."""
    packages = data.get("packages") or []
    if not packages:
        return {"net_weight_kg": None, "gross_weight_kg": None}
    return {"net_weight_kg": str(sum(Decimal(str(p.get("net_weight_kg") or 0)) for p in packages)),
            "gross_weight_kg": str(sum(Decimal(str(p.get("gross_weight_kg") or 0)) for p in packages))}


def refresh_packing(draft: dict, *, approved: bool = False) -> tuple[dict, dict]:
    """PL 원본/계산 합계 비교 제안을 계산한다. (정규화된 초안, 계약 15.5절 `PackingTotals`) 반환."""
    normalized = normalize_packing_inputs(draft)
    check = reconcile_packing(normalized)  # packing_review 래퍼(_packing_input_issues 포함)
    changes = packing_total_changes(normalized, check)
    totals = {"quantities": dict(check["quantities"]),
              "quantity_complete": check["quantity_complete"],
              "calculated": dict(check["calculated"]),
              "packages_total": _packages_total(normalized),
              "issues": list(check["issues"]),
              "discrepancies": list(check["discrepancies"]),
              "changes": changes,
              "approved": approved}
    return normalized, totals


def finalize_draft(draft: dict, *, approved: bool = False) -> dict:
    """검증·계산을 (다시) 돌려 저장 가능한 초안으로 확정한다. PL은 합계 비교 제안을 채운다.

    원본/계산 합계 차이·검토 입력 정규화 오류는 `blocking_issues`에 남아 `needs_input`이 된다
    (원본 `validate_and_calculate`의 PL 차단 동작 그대로). 원본 계약 15.5절의 status 규칙
    "PL 합계 미승인이면 needs_input"은 이 차단으로 이루어진다 — 차이가 없는 PL은 승인 없이도
    `ready`이되, 발송 조건(15.6절)은 `packing_totals.approved`를 본다.
    """
    result = dict(validate_and_calculate(draft, issuer_key=issuer_key_of(draft)))
    if result.get("document_type") == "PL":
        _, totals = refresh_packing(result, approved=approved)
        result["packing_totals"] = totals
        for issue in totals["issues"]:
            message = "Packing: " + issue
            if issue not in result["blocking_issues"] and message not in result["blocking_issues"]:
                result["blocking_issues"].append(message)
    if result.get("document_type") == "CI":
        # 계약 15.5절 파이프라인 마지막 단계: CI 근거 문제(PI 원문 금액 불일치 등)도 차단 항목에 더한다.
        from app.trade.ci_import import ci_import_issues
        for issue in ci_import_issues(result):
            if issue not in result["blocking_issues"]:
                result["blocking_issues"].append(issue)
    if result["blocking_issues"]:
        result["ready_for_issue"] = False
        result["status"] = "needs_input"
    return result


def _log(draft: dict, action: str, **extra) -> list[dict]:
    entry = {"action": action, "at": utcnow().isoformat()}
    entry.update(extra)
    return [*draft.get("packing_approval_log", []), entry]


def save_trade_document(database, *, user_id: int, thread_id: str, draft: dict,
                        run_id: str = "", deal_terms_id: int | None = None) -> dict:
    """무역서류 초안을 검증·저장한다(PL은 합계 비교 제안 저장). 문서번호는 사용자별 채번·잠금."""
    doc_kind = str(draft.get("document_type") or "")
    if doc_kind not in DOC_KINDS:
        raise ValueError("문서 종류는 PI·PO·CI·PL이어야 합니다")
    finalized = finalize_draft(draft, approved=bool((draft.get("packing_totals") or {}).get("approved")))
    if doc_kind == "PL":
        finalized.setdefault("packing_approval_log", [])
    today = utcnow().date()
    # Postgres는 사용자 행 잠금으로 번호 생성을 직렬화한다. SQLite는 유일 제약으로 재시도(create_quote와 같은 방식).
    for attempt in range(3):
        try:
            with database.session() as session:
                user = session.scalar(select(User).where(User.id == user_id).with_for_update())
                if user is None:
                    raise ValueError("사용자를 찾을 수 없습니다")
                prefix = f"{doc_kind}-{today:%Y%m%d}-"
                numbers = session.scalars(select(TradeDocument.doc_no).where(
                    TradeDocument.user_id == user_id, TradeDocument.doc_no.startswith(prefix),
                )).all()
                sequence = max((int(number[len(prefix):]) for number in numbers), default=0) + 1
                row = TradeDocument(user_id=user_id, thread_id=thread_id, run_id=run_id,
                                    deal_terms_id=deal_terms_id, doc_kind=doc_kind,
                                    doc_no=f"{prefix}{sequence:03d}", draft=finalized,
                                    status=finalized["status"])
                session.add(row)
                session.flush()
                finalized = {**finalized, "trade_doc_id": row.id, "doc_no": row.doc_no,
                             "doc_kind": row.doc_kind}
                row.draft = finalized
            return finalized
        except IntegrityError:
            if attempt == 2:
                raise
    raise AssertionError("도달하지 않는다")


def _owned_draft(session, user_id: int, trade_doc_id: int) -> TradeDocument | None:
    return session.scalar(select(TradeDocument).where(
        TradeDocument.id == trade_doc_id, TradeDocument.user_id == user_id))


def _store(session, row: TradeDocument, finalized: dict) -> dict | None:
    """조건부 UPDATE로 저장한다. 이미 보내거나 중간에 바뀐 문서는 저장하지 않고 `None`."""
    claimed = session.execute(
        update(TradeDocument)
        .where(TradeDocument.id == row.id, TradeDocument.user_id == row.user_id,
               TradeDocument.status != "sent")
        .values(draft=finalized, status=finalized["status"])
        .execution_options(synchronize_session=False)
    ).rowcount
    return finalized if claimed == 1 else None


def approve_packing_totals(user_id: int, trade_doc_id: int, *, database) -> dict | None:
    """PL 원본/계산 합계 차이의 명시적 승인(계약 15.5절 (1)~(4)). 승인할 수 없으면 `None`."""
    with _user_lock(database, user_id):
        with database.session() as session:
            row = _owned_draft(session, user_id, trade_doc_id)
            if row is None or row.doc_kind != "PL" or row.status == "sent":
                return None
            draft = row.draft
            if not isinstance(draft, dict):  # ERR-13 대응: 잘못 저장된 구조는 승인 대상이 아니다
                return None
            if (draft.get("packing_totals") or {}).get("approved"):
                return draft  # 이미 승인됐다: 다시 적용·기록하지 않는다(중복 방지)
            # (1) 저장된 초안을 다시 확인한다. 검증 오류·수량 불완전면 승인하지 않는다.
            check = reconcile_packing(normalize_packing_inputs(draft))
            if check["issues"] or not check["quantity_complete"]:
                return None
            # (2) 승인 적용(원본 합계 보존, 계산 가능한 합계만 적용)
            try:
                approved_data = apply_approved_packing_totals(draft)
            except ValueError:
                return None
            # (3)+(4) 재검증·합계 재계산(approved=True)·기록·저장
            finalized = finalize_draft(approved_data, approved=True)
            finalized["packing_approval_log"] = _log(draft, "approved")
            return _store(session, row, finalized)


def cancel_packing_approval(user_id: int, trade_doc_id: int, *, database) -> dict | None:
    """PL 합계 승인을 취소하고 원본 합계로 되돌린다(다시 승인 대상)."""
    with _user_lock(database, user_id):
        with database.session() as session:
            row = _owned_draft(session, user_id, trade_doc_id)
            if row is None or row.doc_kind != "PL" or row.status == "sent":
                return None
            draft = row.draft
            if not isinstance(draft, dict):  # ERR-13 대응: 잘못 저장된 구조는 취소 대상이 아니다
                return None
            if not (draft.get("packing_totals") or {}).get("approved"):
                return draft  # 승인이 없다: 바꿀 것이 없다
            original = draft.get("_packing_original_totals") or {}
            restored = {**draft}
            for field in PACKING_SOURCE_FIELDS:
                restored[field] = original.get(field)
            for key in ("_packing_original_totals", "_packing_totals_approved", "_packing_approved_quantities"):
                restored.pop(key, None)
            finalized = finalize_draft(restored, approved=False)
            finalized["packing_approval_log"] = _log(draft, "cancelled")
            return _store(session, row, finalized)


def revise_trade_document(user_id: int, trade_doc_id: int, values: dict, *, database) -> dict | None:
    """빠진 문서값을 넣어(`apply_review_value`) 재검증·저장한다(계약 15.5절). 키는 점 표기
    (예: `document_number`, `buyer.legal_name`, `items.0.unit_price`)."""
    with _user_lock(database, user_id):
        with database.session() as session:
            row = _owned_draft(session, user_id, trade_doc_id)
            if row is None or row.status == "sent":
                return None
            draft = row.draft
            if not isinstance(draft, dict):  # ERR-13 대응: 잘못 저장된 구조는 수정 대상이 아니다
                return None
            draft = deepcopy(draft)  # ORM 인스턴스를 직접 바꾸지 않는다(저장은 조건부 UPDATE로)
            changed = []
            for key, value in (values or {}).items():
                path = tuple(int(part) if part.isdigit() else part for part in str(key).split("."))
                field = ReviewField(path, label=str(key))
                before = field_value(draft, field)
                apply_review_value(draft, field, value)
                if field_value(draft, field) != before:
                    changed.append(str(key))
            if not changed:
                return draft
            was_approved = bool((draft.get("packing_totals") or {}).get("approved"))
            # 품목·원본 합계 값을 고치면 승인을 다시 받는다(원본 합계 스냅숏도 새로 만든다).
            packing_touched = row.doc_kind == "PL" and any(
                key == "items" or key.startswith("items.") or key in PACKING_SOURCE_FIELDS
                for key in changed)
            if packing_touched:
                draft.pop("_packing_original_totals", None)
                draft.pop("_packing_totals_approved", None)
                draft.pop("_packing_approved_quantities", None)
            finalized = finalize_draft(draft, approved=was_approved and not packing_touched)
            if row.doc_kind == "PL":
                finalized["packing_approval_log"] = _log(draft, "revised", fields=changed)
            return _store(session, row, finalized)
