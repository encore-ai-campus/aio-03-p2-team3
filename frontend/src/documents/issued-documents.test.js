import assert from "node:assert/strict"
import test from "node:test"

import { normalizeIssued, searchIssued, formatTotal } from "./useIssuedDocuments.js"

test("normalizeIssued는 4종 응답을 최근 등록순 한 줄로 합친다", () => {
  const rows = normalizeIssued({
    pi: [{ document_id: 2, document_type: "PI", document_number: "PI-2026-1102", doc_no: "PI-20261118-001",
      revision: 3, status: "sent", currency: "USD", total: "12400", counterparty: "Global Trade Co",
      created_at: "2026-11-18T02:24:00+00:00" }],
    po: [{ document_id: 5, document_type: "PO", document_number: null, doc_no: "PO-20261117-002",
      revision: 1, status: "needs_input", currency: null, total: null, counterparty: null,
      created_at: "2026-11-17T08:00:00+00:00" }],
  })
  assert.equal(rows.length, 2)
  assert.deepEqual(rows.map((row) => row.id), [2, 5]) // created_at 내림차순
  assert.equal(rows[0].kindLabel, "PI")
  assert.equal(rows[1].number, "PO-20261117-002") // 문서번호 없으면 내부 번호
  assert.equal(rows[1].counterparty, null)
})

test("searchIssued는 문서번호·거래처·종류에서 찾는다", () => {
  const rows = normalizeIssued({
    ci: [
      { document_id: 1, document_type: "CI", document_number: "CI-1", doc_no: "CI-x", revision: 1,
        status: "ready", counterparty: "Global Trade Co", created_at: "2026-11-18T00:00:00+00:00" },
      { document_id: 2, document_type: "CI", document_number: "CI-2", doc_no: "CI-y", revision: 1,
        status: "sent", counterparty: "Seafood Ltd", created_at: "2026-11-17T00:00:00+00:00" },
    ],
  })
  assert.equal(searchIssued(rows, "global").length, 1)
  assert.equal(searchIssued(rows, "ci-2")[0].id, 2)
  assert.equal(searchIssued(rows, "  ").length, 2) // 빈 검색어는 전체
})

test("formatTotal은 숫자면 천 단위 구분을 붙이고 통화를 함께 돌려준다", () => {
  assert.deepEqual(formatTotal({ total: "12400", currency: "USD" }), { amount: "12,400", currency: "USD" })
  assert.equal(formatTotal({ total: null }), null)
})
