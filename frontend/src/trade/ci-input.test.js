import assert from "node:assert/strict"
import test from "node:test"
import { canCreateCI, ciDraft, ciMissing, ciPayload, mergeCIPreparation, sourceLabel, standaloneCINext } from "./ci-input.js"

test("미승인 PI 선택과 서버 CI 생성 가능 상태를 구분하며 정확한 승인 버전만 허용한다", () => {
  const draft = ciDraft({ source_pi_id: 1, source_revision: 1, document_number: "CI-DEMO" })
  const source = { source_pi_id: 1, source_revision: 1, approved: false, checked: true, missing_fields: [], issues: [] }
  assert.equal(sourceLabel(source), "PI 승인 필요")
  assert(!canCreateCI(source, draft))
  source.approved = true
  assert(canCreateCI(source, draft))
  assert(!canCreateCI({ ...source, checked: false }, draft))
  assert(!canCreateCI(source, { ...draft, source_revision: 2 }))
})

test("PI 보완·선택 변경과 추출 후에도 사전 입력을 보존하고 원본 사실·승인 플래그는 전송하지 않는다", () => {
  const prepared = ciDraft({ document_number: "CI-MANUAL", shipment_reference: "Manual shipment", country_of_origin: "" })
  const merged = mergeCIPreparation({ source_pi_id: 2, source_revision: 3, document_number: "AI-CI", country_of_origin: "Korea" }, prepared)
  assert.equal(merged.document_number, "CI-MANUAL")
  assert.equal(merged.shipment_reference, "Manual shipment")
  assert.equal(merged.country_of_origin, "Korea")
  const payload = ciPayload({ ...merged, items: [], bank: {}, approved: true })
  assert(!("bank" in payload) && !("items" in payload) && !("approved" in payload))
  assert.equal(payload.source_revision, 3)
  assert.deepEqual(ciMissing(merged), [])
})

test("단독 CI 추출 뒤 채워진 단계를 건너뛰고 선적 빈칸만 묻는다", () => {
  const draft = { product_family: "other", currency: "USD", document_number: "CI-1", incoterms: "FOB",
    shipment_reference: "", country_of_origin: "Korea", buyer: { legal_name: "Buyer", address: "Address" },
    seller: { legal_name: "Seller", address: "Address" }, items: [{ product_name: "Item", quantity: "1", unit: "PCS",
      unit_price: "5", price_basis: "PCS", discount_percent: "0" }] }
  assert.deepEqual(standaloneCINext(draft), { key: "terms", fields: ["shipment_reference"] })
  draft.shipment_reference = "SHIP"
  assert.deepEqual(standaloneCINext(draft), { key: "review", fields: null })
})
