import assert from "node:assert/strict"
import test from "node:test"
import { emptyPO, poDraft, poMissing, poNextScreen, poPayload } from "./po-input.js"

const purchase = () => poDraft({
  product_family: "other", document_number: "PO-DEMO", currency: "USD",
  seller: { legal_name: "Demo supplier", address: "Demo supplier address" },
  buyer: { legal_name: "Demo buyer", address: "Demo buyer address" },
  incoterms: "FOB Busan", payment_terms: "T/T",
  items: [{ product_name: "Demo pump", quantity: "12.000000000001", unit: "PCS",
    unit_price: "8.25", price_basis: "PCS", discount_percent: "0" }],
})

test("PO는 공급처부터 시작하고 추출 후에는 누락된 단계만 질문한다", () => {
  assert.equal(poNextScreen(emptyPO()).key, "seller")
  const draft = purchase()
  assert.equal(poNextScreen(draft).key, "review")
  draft.seller.address = "TBD"
  draft.payment_terms = ""
  assert.deepEqual(poNextScreen(draft), { key: "seller", fields: ["seller.address"] })
  draft.seller.address = "Confirmed supplier address"
  assert.deepEqual(poNextScreen(draft, 0), { key: "terms", fields: ["payment_terms"] })
})

test("PO는 PI 샘플 필드를 보내지 않고 십진수·명시적 매입 단가 확인을 보존한다", () => {
  const draft = purchase()
  draft.items[0].paid_quantity = draft.items[0].quantity
  draft.items[0].confirm_price_override = true
  draft.items[0].is_sample = true
  const row = poPayload(draft).items[0]
  assert.equal(row.paid_quantity, "12.000000000001")
  assert.equal(row.unit_price, "8.25")
  assert.equal(row.confirm_price_override, true)
  assert(!("rowId" in row))
  assert(!("is_sample" in row))
  draft.items[0].unit_price = "0.00"
  assert(!poMissing(draft).includes("items.0.unit_price"))
})
