const HEADER_FIELDS = ["product_family", "document_number", "incoterms", "remarks", "ship_to", "bill_to", "shipment_reference", "hs_code",
  "actual_package_count", "container_count", "declared_net_weight_kg", "declared_gross_weight_kg", "declared_volume_cbm", "declared_total_quantity", "declared_total_quantity_unit"]
export const PACKAGE_FIELDS = ["package_type", "package_count", "net_weight_kg", "gross_weight_kg", "dimensions", "shipping_marks"]
const ITEM_FIELDS = [...PACKAGE_FIELDS, "product_name", "product_code", "capacity", "quantity", "unit", "volume_cbm", "source"]
const PARTY_FIELDS = ["legal_name", "address", "contact", "phone", "email", "registration_details"]
export const PACKING_TOTAL_FIELDS = [["actual_package_count","포장 수","package_count"],["declared_net_weight_kg","순중량 kg","net_weight_kg"],
  ["declared_gross_weight_kg","총중량 kg","gross_weight_kg"],["declared_volume_cbm","부피 CBM","volume_cbm"]]

export function newPLItem(values = {}) { return { rowId: crypto.randomUUID(), product_name: "", quantity: "", unit: "PCS", ...values } }
export function newPackage(values = {}) { return { rowId: crypto.randomUUID(), ...values } }
export function emptyPL() {
  return { ...Object.fromEntries(HEADER_FIELDS.map((key) => [key, ""])), product_family: "other", buyer: {}, seller: {}, items: [newPLItem()], packages: [] }
}
export function plDraft(input = {}) {
  return { ...emptyPL(), ...Object.fromEntries(HEADER_FIELDS.map((key) => [key, input[key] ?? (key === "product_family" ? null : "")])),
    buyer: { ...input.buyer }, seller: { ...input.seller }, items: (input.items ?? []).map(newPLItem), packages: (input.packages ?? []).map(newPackage) }
}
export function plPayload(draft) {
  const pick = (row, fields) => Object.fromEntries(fields.map((key) => [key, row[key] === "" || row[key] == null ? null : row[key]]))
  return { ...pick(draft, HEADER_FIELDS), buyer: pick(draft.buyer, PARTY_FIELDS), seller: pick(draft.seller, PARTY_FIELDS),
    items: draft.items.map((row) => pick(row, ITEM_FIELDS)), packages: draft.packages.map((row) => pick(row, PACKAGE_FIELDS)) }
}
export const PL_STEPS = [
  { key: "buyer", label: "거래처", question: "어느 회사에 보내나요?", note: "구매자의 영문 회사명과 주소를 알려주세요." },
  { key: "seller", label: "판매자", question: "판매자 정보를 확인해 주세요", note: "발행 회사의 판매자 정보를 확인해 주세요." },
  { key: "packing", label: "품목·포장", question: "어떻게 포장해서 보내나요?", note: "품목 수량과 포장 행을 입력해 주세요. 서로 다른 단위는 나누어 확인해요." },
  { key: "terms", label: "선적 조건·합계", question: "선적 조건과 원본 합계를 알려주세요", note: "원본에 적힌 합계와 단위·컨테이너 표기를 그대로 입력해 주세요." },
]
export function plSectionFor(path) {
  if (path.startsWith("buyer.")) return "buyer"
  if (path.startsWith("seller.")) return "seller"
  return /^(?:items|packages|packing)(?:\.|$)/.test(path) ? "packing" : "terms"
}
export function plMissing(draft) {
  const paths = ["product_family", "document_number", "incoterms", "shipment_reference"]
  for (const role of ["buyer","seller"]) for (const key of ["legal_name","address"]) paths.push(`${role}.${key}`)
  if (!draft.items.length) paths.push("items")
  draft.items.forEach((row,index) => { for (const key of ["product_name","quantity","unit"]) paths.push(`items.${index}.${key}`) })
  return paths.filter((path) => path === "items" || /^(?:\s*|tbd|unknown|not provided|to be confirmed|n\/a)$/i.test(String(path.split(".").reduce((value,key) => value?.[key], draft) ?? "").trim()))
}
export function plNextScreen(draft, after = -1) {
  const missing = plMissing(draft)
  const step = PL_STEPS.find((entry,index) => index > after && missing.some((path) => plSectionFor(path) === entry.key))
  return step ? { key: step.key, fields: missing.filter((path) => plSectionFor(path) === step.key) } : { key: "review", fields: null }
}

export function canApprovePacking(view, document, dirty) {
  const totals = view?.payload.document.packing_totals
  return Boolean(view && document && !dirty && view.document_id === document.document_id && view.revision === document.revision
    && totals?.quantity_complete === true && totals.issues.length === 0 && !totals.approved)
}
