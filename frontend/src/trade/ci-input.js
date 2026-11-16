export const CI_FIELDS = ["document_number", "shipment_reference", "country_of_origin", "incoterms", "ship_to", "bill_to", "remarks"]

export function emptyCI() {
  return { source_pi_id: null, source_revision: null, ...Object.fromEntries(CI_FIELDS.map((key) => [key, ""])) }
}

export function ciDraft(input = {}) {
  return Object.fromEntries(Object.keys(emptyCI()).map((key) => [key, input[key] ?? emptyCI()[key]]))
}

export function ciPayload(draft) {
  return { source_pi_id: draft.source_pi_id, source_revision: draft.source_revision,
    ...Object.fromEntries(CI_FIELDS.map((key) => [key, draft[key] === "" ? null : draft[key]])) }
}

export function ciMissing(draft) {
  return ["document_number", "shipment_reference", "country_of_origin"].filter((key) =>
    draft[key] == null || /^(?:\s*|tbd|unknown|not provided|to be confirmed|n\/a)$/i.test(draft[key].trim()))
}

export function standaloneCINext(draft, after = -1) {
  const missing = [...piMissing(draft).filter((path) => path !== "payment_terms" &&
    (!path.endsWith(".unit_price") || !draft.items[Number(path.split(".")[1])]?.unit_price)),
  ...ciMissing(draft)]
  const keys = ["buyer", "seller", "items", "terms"]
  const section = (path) => ciMissing(draft).includes(path) ? "terms" : piSectionFor(path)
  const key = keys.find((value, index) => index > after && missing.some((path) => section(path) === value))
  return key ? { key, fields: [...new Set(missing.filter((path) => section(path) === key))] } : { key: "review", fields: null }
}

export function mergeCIPreparation(input, prepared) {
  const draft = ciDraft(input)
  for (const key of CI_FIELDS) if (prepared[key] != null && prepared[key] !== "") draft[key] = prepared[key]
  return draft
}

export function canCreateCI(source, draft) {
  return source?.checked === true && source.approved === true
    && source.source_pi_id === draft.source_pi_id && source.source_revision === draft.source_revision
}

export function sourceLabel(source) {
  if (source.approved) return "승인 완료"
  return source.missing_fields.length || source.issues.length ? "정보 보완 필요" : "PI 승인 필요"
}

export function piFieldLabel(path) {
  const labels = { buyer: "구매자", seller: "판매자", legal_name: "회사명", address: "주소", items: "품목",
    product_name: "상품명", quantity: "수량", paid_quantity: "유상 수량", unit: "단위", unit_price: "단가",
    discount_percent: "할인율", price_basis: "가격 기준", product_family: "상품군", document_number: "문서번호",
    currency: "통화", incoterms: "납품 조건", payment_terms: "지급 조건" }
  return path.split(".").map((key) => /^\d+$/.test(key) ? `${Number(key) + 1}번` : labels[key] ?? key).join(" · ")
}
import { piMissing, piSectionFor } from "./pi-input.js"
