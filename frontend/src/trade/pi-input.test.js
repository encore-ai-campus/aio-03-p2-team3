import assert from "node:assert/strict"
import test from "node:test"
import { emptyPI, piDraft, piMissing, piNextScreen, piPayload } from "./pi-input.js"

const extracted = () => piDraft({
  product_family: "other", document_number: "PI-DEMO", currency: "USD",
  buyer: { legal_name: "Harbor Demo Trading", address: "Demo buyer address" },
  seller: { legal_name: "Summit Demo Export", address: "Demo seller address" },
  incoterms: "FOB Busan", payment_terms: "T/T in advance",
  items: [{ product_name: "Demo pump", quantity: "10", paid_quantity: "10", unit: "PCS",
    unit_price: "8.25", price_basis: "PCS", discount_percent: "0", is_sample: false }],
})

test("추출이 끝난 PI는 선택 연락처를 다시 묻지 않고 전체 확인으로 간다", () => {
  assert.deepEqual(piNextScreen(extracted()), { key: "review", fields: null })
  const draft = extracted()
  draft.payment_terms = null
  assert.deepEqual(piNextScreen(draft), { key: "terms", fields: ["payment_terms"] })
  draft.payment_terms = "T/T in advance"
  assert.equal(piNextScreen(draft).key, "review")
})

test("빈칸만 묻고 답한 뒤에는 완료된 거래처와 품목 단계를 건너뛴다", () => {
  const draft = extracted()
  draft.buyer.address = "TBD"
  draft.payment_terms = ""
  assert.deepEqual(piNextScreen(draft), { key: "buyer", fields: ["buyer.address"] })
  draft.buyer.address = "Demo delivery address"
  assert.deepEqual(piNextScreen(draft, 0), { key: "terms", fields: ["payment_terms"] })
})

test("빈 상품군·빈 품목·가격 기준·샘플의 0원은 서로 구분한다", () => {
  const draft = extracted()
  draft.product_family = null
  draft.items[0].price_basis = null
  draft.items[0].unit_price = "0.00"
  assert.deepEqual(piNextScreen(draft), { key: "items", fields: ["items.0.price_basis", "items.0.unit_price"] })
  draft.items[0].is_sample = true
  assert(!piMissing(draft).includes("items.0.unit_price"))
  assert(piMissing(draft).includes("product_family"))
  draft.items = []
  assert(piMissing(draft).includes("items"))
  assert.equal(piNextScreen(emptyPI()).key, "buyer")
})

test("표 편집 데이터는 십진수와 명시적 단가 확인을 보존하고 화면 ID는 전송하지 않는다", () => {
  const draft = extracted()
  draft.items[0].quantity = "12.000000000001"
  draft.items[0].paid_quantity = draft.items[0].quantity
  draft.items[0].confirm_price_override = true
  const payload = piPayload(draft)
  assert.equal(payload.items[0].paid_quantity, "12.000000000001")
  assert.equal(payload.items[0].confirm_price_override, true)
  assert(!("rowId" in payload.items[0]))
  assert(draft.items[0].rowId)
})
