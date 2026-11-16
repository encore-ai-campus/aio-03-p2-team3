export function emptyPO() {
  return { product_family: "other", document_number: "", currency: "USD", buyer: {}, seller: {},
    incoterms: "", payment_terms: "", remarks: "", ship_to: "", bill_to: "", items: [newPOItem()] }
}

export function newPOItem(values = {}) {
  return { rowId: crypto.randomUUID(), product_name: "", capacity: "", quantity: "", unit: "PCS",
    discount_percent: "0", confirm_price_override: false, ...values }
}

export function poDraft(input) {
  return { ...emptyPO(), ...input, items: (input.items ?? []).map((item) => newPOItem(item)) }
}

export function poPayload(draft) {
  return { ...draft, currency: draft.currency || null, product_family: draft.product_family || null,
    items: draft.items.map((row) => {
      const item = { ...row }
      delete item.rowId
      delete item.is_sample
      return item
    }) }
}

export const PO_STEPS = [
  { key: "seller", label: "공급처", question: "어느 회사에서 구매하나요?", note: "공급처의 영문 회사명과 주소를 알려주세요." },
  { key: "buyer", label: "구매자", question: "구매자 정보를 확인해 주세요", note: "PO의 구매자는 문서를 발행하는 우리 회사입니다." },
  { key: "items", label: "품목", question: "어떤 상품을 얼마나 구매하나요?", note: "품목과 수량·매입 단가를 표에서 바로 수정하세요." },
  { key: "terms", label: "거래 조건", question: "거래 조건을 알려주세요", note: "문서번호와 납품·지급 조건을 확인해 주세요." },
]

export function poSectionFor(path) {
  if (path.startsWith("buyer.")) return "buyer"
  if (path.startsWith("seller.")) return "seller"
  return path === "items" || path.startsWith("items.") ? "items" : "terms"
}

function blank(value) {
  return value == null || /^(?:\s*|not provided|to be confirmed|to confirm|tbd|unknown|none|null|n\/a)$/i.test(String(value).trim())
}

// 질문할 빈칸만 고른다. 금액·가격 검증과 발급 가능 여부는 기존 서버가 판단한다.
export function poMissing(draft) {
  const paths = ["product_family", "document_number", "currency", "incoterms", "payment_terms"]
  for (const role of ["buyer", "seller"]) {
    for (const key of ["legal_name", "address"]) paths.push(`${role}.${key}`)
  }
  if (!draft.items.length) paths.push("items")
  draft.items.forEach((row, index) => {
    for (const key of ["product_name", "unit", "price_basis", "discount_percent"]) paths.push(`items.${index}.${key}`)
    if (blank(row.paid_quantity) && blank(row.quantity)) paths.push(`items.${index}.quantity`)
    if (blank(row.unit_price)) paths.push(`items.${index}.unit_price`)
  })
  return paths.filter((path) => path === "items" || path.endsWith(".unit_price") || blank(path.split(".").reduce((value, key) => value?.[key], draft)))
}

export function poNextScreen(draft, after = -1) {
  const missing = poMissing(draft)
  const step = PO_STEPS.find((entry, index) => index > after && missing.some((path) => poSectionFor(path) === entry.key))
  return step ? { key: step.key, fields: missing.filter((path) => poSectionFor(path) === step.key) } : { key: "review", fields: null }
}
