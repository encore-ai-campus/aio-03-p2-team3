import assert from "node:assert/strict"
import test from "node:test"
import { canApprovePacking, plDraft, plMissing, plNextScreen, plPayload } from "./pl-input.js"

test("PL은 원본 표기·서로 다른 단위·두 포장 배열을 보존하고 가격·승인 상태는 전송하지 않는다", () => {
  const draft = plDraft({ product_family: "other", document_number: "PL-DEMO", shipment_reference: "SHIP",
    incoterms: "FOB Busan", buyer: { legal_name: "Demo buyer", address: "Buyer address" }, seller: { legal_name: "Demo seller", address: "Seller address" },
    container_count: "2 x 40FT", declared_total_quantity: "1,000 PCS", declared_net_weight_kg: "12.000000000001 kg",
    items: [{ product_name: "Demo A", quantity: "1000", unit: "PCS", unit_price: "9", volume_cbm: "1.2" }, { product_name: "Demo B", quantity: "50", unit: "KG" }],
    packages: [{ package_type: "PALLET", package_count: "2", net_weight_kg: "100", gross_weight_kg: "110" }] })
  const payload = plPayload({ ...draft, currency: "USD", packing_totals: {}, _packing_totals_approved: true })
  assert.equal(payload.container_count, "2 x 40FT")
  assert.equal(payload.declared_net_weight_kg, "12.000000000001 kg")
  assert.deepEqual(payload.items.map((row) => row.unit), ["PCS", "KG"])
  assert.equal(payload.packages.length, 1)
  assert(!("unit_price" in payload.items[0]) && !("rowId" in payload.packages[0]))
  assert(!("packing_totals" in payload) && !("currency" in payload))
  draft.container_count = ""
  assert(!plMissing(draft).includes("container_count"))
  assert.equal(plNextScreen(draft).key, "review")
  draft.buyer.address = ""
  assert.deepEqual(plNextScreen(draft), { key: "buyer", fields: ["buyer.address"] })
})

test("PL 합계는 원본과 달라도 승인할 수 있고 잘못된 행·미저장·오래된 버전은 막는다", () => {
  const document = { document_id: 5, revision: 2 }
  const view = { ...document, payload: { document: { packing_totals: {
    approved: false, issues: [], discrepancies: ["source total differs"], quantity_complete: true,
  } } } }
  assert(canApprovePacking(view,document,false))
  assert(!canApprovePacking(view,document,true))
  assert(!canApprovePacking(view,{ ...document, revision: 3 },false))
  view.payload.document.packing_totals.issues = ["net weight exceeds gross weight"]
  assert(!canApprovePacking(view,document,false))
  view.payload.document.packing_totals.issues = []
  view.payload.document.packing_totals.quantity_complete = false
  assert(!canApprovePacking(view,document,false))
})
