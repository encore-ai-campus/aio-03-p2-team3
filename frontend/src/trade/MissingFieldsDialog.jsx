import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"

const LABELS = {
  product_family: "상품군", document_number: "문서번호", document_type: "문서 종류", currency: "통화",
  incoterms: "납품 조건", payment_terms: "지급 조건", issue_date: "발행일", ship_to: "배송지", bill_to: "청구지",
  country_of_origin: "원산지", shipment_reference: "선적 참조", hs_code: "HS 코드",
  container_count: "컨테이너 수", actual_package_count: "실제 포장 수", declared_net_weight_kg: "원본 순중량 (kg)",
  declared_gross_weight_kg: "원본 총중량 (kg)", declared_volume_cbm: "원본 부피 (CBM)",
  declared_total_quantity: "원본 총수량", declared_total_quantity_unit: "원본 수량 단위",
  legal_name: "회사명 (영문)", address: "주소 (영문)", contact: "담당자", phone: "전화",
  email: "이메일", registration_details: "등록 정보", product_name: "품목명 (영문)",
  product_code: "상품 코드", capacity: "용량·규격", quantity: "수량", paid_quantity: "유상 수량",
  unit: "단위", unit_price: "단가", discount_percent: "할인율 (%)", free_quantity: "무상 수량",
  promotion: "프로모션 조건", price_basis: "가격 기준", package_type: "포장 종류",
  package_count: "포장 수", net_weight_kg: "순중량 (kg)", gross_weight_kg: "총중량 (kg)",
  volume_cbm: "부피 (CBM)", dimensions: "규격", shipping_marks: "화인", remarks: "비고",
}

function readPath(value, path) {
  return path.split(".").reduce((current, key) => current?.[key], value)
}

function validPath(value, path) {
  if (path === "items") return false
  if (!/^(buyer|seller)\.[a-z_]+$|^(items|packages)\.\d+\.[a-z_]+$|^[a-z_]+$/.test(path)) return false
  const parts = path.split(".")
  const last = parts.pop()
  const parent = parts.length ? readPath(value, parts.join(".")) : value
  if (!parent || typeof parent !== "object") return false
  if ((parts[0] === "items" || parts[0] === "packages") && !parent) return false
  return Object.hasOwn(parent, last) || Object.hasOwn(LABELS, last)
}

export function updateMissingField(value, path, nextValue) {
  const parts = path.split(".")
  const copy = structuredClone(value)
  let target = copy
  for (const key of parts.slice(0, -1)) target = target[key]
  target[parts.at(-1)] = nextValue
  if (parts[0] === "items") {
    if (parts.at(-1) === "quantity") target.paid_quantity = nextValue
  }
  if (Array.isArray(copy.conflicts)) {
    copy.conflicts = copy.conflicts.filter((message) => {
      const conflict = sourceConflictDetails(message, copy)
      return !(conflict?.clearable && conflict.fields.includes(path))
    })
  }
  return copy
}

function sourceConflictDetails(raw, draft) {
  const message = String(raw ?? "").trim()
  const fieldNames = {
    "legal name": "legal_name", address: "address", phone: "phone", email: "email",
    "registration details": "registration_details", incoterms: "incoterms", "payment terms": "payment_terms",
    "document number": "document_number", "issue date": "issue_date", "shipment reference": "shipment_reference",
    "country of origin": "country_of_origin", "ship to": "ship_to", "bill to": "bill_to",
    "product name": "product_name", "product code": "product_code", capacity: "capacity",
    quantity: "quantity", "paid quantity": "paid_quantity", "free quantity": "free_quantity",
    "shipped quantity": "shipped_quantity", "unit price": "unit_price", "discount percent": "discount_percent",
  }
  let match = /^Item (\d+) (product name|product code|capacity|quantity|paid quantity|free quantity|shipped quantity|unit price|discount percent) was not found in its source quote; confirm the value$/i.exec(message)
  if (match) {
    const index = Number(match[1]) - 1
    const key = fieldNames[match[2].toLowerCase()]
    const path = `items.${index}.${key}`
    const name = draft.items?.[index]?.product_name || `품목 ${index + 1}`
    const value = readPath(draft, path)
    return { message: `품목 ${index + 1} (${name}) · ${LABELS[key]} 입력값${value ? ` ‘${value}’` : ""}이 원문 인용에서 확인되지 않습니다. 원문과 대조해 수정하세요.`, fields: [path], clearable: true }
  }
  match = /^(Buyer|Seller) (legal name|address|phone|email|registration details) was not found verbatim in the prompt; confirm it$/i.exec(message)
  if (match) {
    const path = `${match[1].toLowerCase()}.${fieldNames[match[2].toLowerCase()]}`
    const value = readPath(draft, path)
    return { message: `${match[1] === "Buyer" ? "구매자" : "판매자"} · ${LABELS[path.split(".")[1]]} 입력값${value ? ` ‘${value}’` : ""}이 원문에서 확인되지 않습니다. 원문과 대조해 수정하세요.`, fields: [path], clearable: true }
  }
  match = /^(Incoterms|Payment terms|Document number|Issue date|Shipment reference|Country of origin|Ship to|Bill to) was not found verbatim in the prompt; confirm it$/i.exec(message)
  if (match) {
    const path = fieldNames[match[1].toLowerCase()]
    const value = readPath(draft, path)
    return { message: `${LABELS[path]} 입력값${value ? ` ‘${value}’` : ""}이 원문에서 확인되지 않습니다. 원문과 대조해 수정하세요.`, fields: [path], clearable: true }
  }
  match = /^Item (\d+) has no verifiable exact quote from the prompt; confirm its extracted facts$/i.exec(message)
  if (match) {
    const index = Number(match[1]) - 1
    const name = draft.items?.[index]?.product_name || `품목 ${index + 1}`
    const fields = ["product_name", "capacity", "product_code", "quantity", "unit_price"].map((key) => `items.${index}.${key}`)
    return { message: `품목 ${index + 1} (${name})의 원문 근거를 찾지 못했습니다. 품목명·규격·상품 코드·수량·단가를 원문과 대조해 수정하세요.`, fields }
  }
  if (/^Currency was not explicitly identified in the prompt|^More than one currency is explicitly indicated|^Extracted currency .+ conflicts with explicit .+ price evidence/i.test(message)) {
    const value = draft.currency || "미입력"
    return { message: `통화 입력값 ‘${value}’을 원문에서 확인할 수 없거나 원문에 여러 통화가 있습니다. 통화 항목을 원문에 맞게 수정하세요.`, fields: ["currency"], clearable: true }
  }
  if (/^Confirm product code against its exact source quote$/i.test(message)) {
    const fields = (draft.items ?? []).map((_, index) => `items.${index}.product_code`).filter((path) => validPath(draft, path))
    return { message: "품목 상품 코드가 원문에서 확인되지 않습니다. 각 품목의 상품 코드를 원문과 대조해 수정하세요.", fields }
  }
  if (/^A source note is not an exact quote from the prompt; review the translated fields$/i.test(message)) {
    const fields = (draft.items ?? []).flatMap((_, index) => [`items.${index}.product_name`, `items.${index}.capacity`])
      .filter((path) => validPath(draft, path))
    return { message: "추출된 품목명·용량/규격의 원문 인용이 일치하지 않습니다. 해당 품목 정보를 원문과 대조해 수정하세요.", fields }
  }
  if (/^Attached order image has no quoted source evidence|^Order details were extracted from an image/i.test(message)) {
    const fields = (draft.items ?? []).flatMap((_, index) => [`items.${index}.product_name`, `items.${index}.capacity`, `items.${index}.quantity`])
      .filter((path) => validPath(draft, path))
    return { message: "첨부 이미지에서 추출한 품목명·규격·수량을 이미지 원문과 대조해 수정하세요.", fields }
  }
  if (/^Confirm sample designation against its exact source quote$/i.test(message)) {
    return { message: "샘플로 표시된 품목의 원문 근거를 확인하세요. 해당 품목의 샘플 여부를 원문과 대조하세요.", fields: [] }
  }
  if (/^Promotion command is negated or cancelled/i.test(message)) {
    const fields = (draft.items ?? []).map((_, index) => `items.${index}.promotion`).filter((path) => validPath(draft, path))
    return { message: "원문에서 프로모션이 취소되었거나 적용되지 않는 것으로 표시되어 있습니다. 프로모션 조건을 원문에 맞게 수정하세요.", fields }
  }
  if (/^Promotion command target is unclear/i.test(message)) {
    const fields = (draft.items ?? []).map((_, index) => `items.${index}.promotion`).filter((path) => validPath(draft, path))
    return { message: "프로모션을 적용할 품목을 확인할 수 없습니다. 해당 품목의 프로모션 조건을 구체적으로 수정하세요.", fields }
  }
  if (/^Promotion command contains conflicting event ratios/i.test(message)) {
    const fields = (draft.items ?? []).map((_, index) => `items.${index}.promotion`).filter((path) => validPath(draft, path))
    return { message: "프로모션 비율이 서로 다릅니다. 품목별 적용 비율을 원문과 대조해 수정하세요.", fields }
  }
  match = /^(.+) stated price differs from the verified catalog; confirm transaction override$/i.exec(message)
  if (match) {
    const index = (draft.items ?? []).findIndex((item) => item.product_name === match[1])
    if (index >= 0) return { message: `품목 ${index + 1} (${match[1]}) · 단가 ${draft.items[index].unit_price ?? "미입력"}가 등록 단가와 다릅니다. 단가를 수정하거나 수기 단가 사용을 확인하세요.`, fields: [`items.${index}.unit_price`], clearable: true }
  }
  return null
}

function packingIssuePaths(message) {
  let match = /^Packing row (\d+): quantity and unit must be confirmed$/i.exec(message)
  if (match) return [`items.${Number(match[1]) - 1}.quantity`, `items.${Number(match[1]) - 1}.unit`]
  match = /^Packing row (\d+): net weight exceeds gross weight$/i.exec(message)
  if (match) return [`items.${Number(match[1]) - 1}.net_weight_kg`, `items.${Number(match[1]) - 1}.gross_weight_kg`]
  match = /^Packing row (\d+): (package count|net weight|gross weight|CBM) is invalid$/i.exec(message)
  if (match) {
    const key = { "package count": "package_count", "net weight": "net_weight_kg", "gross weight": "gross_weight_kg", cbm: "volume_cbm" }[match[2].toLowerCase()]
    return [`items.${Number(match[1]) - 1}.${key}`]
  }
  match = /^Source (package count|net weight \(kg\)|gross weight \(kg\)|volume \(CBM\)|quantity) total is invalid$/i.exec(message)
  if (match) {
    const key = { "package count": "actual_package_count", "net weight (kg)": "declared_net_weight_kg",
      "gross weight (kg)": "declared_gross_weight_kg", "volume (cbm)": "declared_volume_cbm", quantity: "declared_total_quantity" }[match[1].toLowerCase()]
    return [key]
  }
  if (/^Container count must be a non-negative whole number$/i.test(message)) return ["container_count"]
  if (/^Actual package count must be a positive whole number$/i.test(message)) return ["actual_package_count"]
  if (/^Source total quantity has conflicting units/i.test(message)) return ["declared_total_quantity_unit"]
  match = /^Net weight cannot exceed gross weight for package (\d+)$/i.exec(message)
  if (match) return [`packages.${Number(match[1]) - 1}.net_weight_kg`, `packages.${Number(match[1]) - 1}.gross_weight_kg`]
  match = /^(Package count|Net weight|Gross weight) for package (\d+) must be a whole number$/i.exec(message)
  if (match) return [`packages.${Number(match[2]) - 1}.${{ "package count": "package_count", "net weight": "net_weight_kg", "gross weight": "gross_weight_kg" }[match[1].toLowerCase()]}`]
  if (/^Sum of package counts must equal actual package count$/i.test(message)) return ["actual_package_count", "packages.0.package_count"]
  return []
}

function matchProduct(message, draft) {
  const found = /(?:for|match for) (.+?)(?:;| must|$)/i.exec(message)
  const index = found ? (draft.items ?? []).findIndex((item) => item.product_name?.toLowerCase().includes(found[1].trim().toLowerCase())) : -1
  return index >= 0 ? index : null
}

function issueDetails(raw, draft, kind) {
  const message = String(typeof raw === "string" ? raw : raw?.message ?? "").trim().replace(/^Packing:\s*/i, "")
  const fields = []
  const sourceConflict = sourceConflictDetails(message.replace(/^Resolve conflicting information:\s*/i, ""), draft)
  if (sourceConflict) return sourceConflict
  if (message === "items" || /^At least one line item is required$/i.test(message)) {
    return { message: "품목 항목을 추가하세요.", fields: [], step: kind === "PL" ? "packing" : kind === "CI" ? null : "items", source: kind === "CI" }
  }
  const direct = /^(?:buyer|seller)\.[a-z_]+$|^(?:items|packages)\.\d+\.[a-z_]+$|^[a-z_]+$/.test(message)
  if (direct && validPath(draft, message)) fields.push(message)
  fields.push(...packingIssuePaths(message).filter((path) => validPath(draft, path)))

  let match = /^Valid (?:positive )?number required for (.+?)(?: for item (\d+))?$/i.exec(message)
  if (match && match[2]) {
    const key = { "unit price": "unit_price", quantity: "quantity", "paid quantity": "quantity", "shipped quantity": "quantity",
      "free quantity": "free_quantity", "discount percent": "discount_percent", "package count": "package_count",
      "net weight": "net_weight_kg", "gross weight": "gross_weight_kg", "volume": "volume_cbm" }[match[1].toLowerCase()]
    if (key) fields.push(`items.${Number(match[2]) - 1}.${key}`)
  }
  match = /^(?:Price source|Cosmetics price) for (.+?) must/i.exec(message)
  if (match) {
    const index = matchProduct(`for ${match[1]}`, draft)
    if (index !== null) fields.push(`items.${index}.unit_price`)
  }
  match = /^Confirm missing information: (.+)$/i.exec(message)
  if (match && validPath(draft, match[1])) fields.push(match[1])
  match = /^Resolve conflicting information: Item (\d+) discount percent/i.exec(message)
  if (match) fields.push(`items.${Number(match[1]) - 1}.discount_percent`)
  match = /(?:exact catalog product match|product match) for (.+?)(?:;|$)/i.exec(message)
  if (match) {
    const index = matchProduct(`for ${match[1]}`, draft)
    if (index !== null) {
      fields.push(`items.${index}.product_name`, `items.${index}.capacity`, `items.${index}.product_code`)
      const name = draft.items?.[index]?.product_name || `품목 ${index + 1}`
      const valid = fields.filter((path) => validPath(draft, path))
      const canConfirmManualItem = kind !== "CI" || draft.mode === "standalone"
      if (!canConfirmManualItem) return { message: `${name}이(가) 등록 품목과 일치하지 않습니다. 원본 PI의 품목 정보를 확인하세요.`,
        fields: [], source: true }
      return { message: `${name}이(가) 등록 품목과 일치하지 않습니다. 등록 정보를 확인하거나 수기 입력을 선택하세요.`, fields: valid,
        catalogMatch: true, confirmPath: `items.${index}.confirm_product_override` }
    }
  }
  match = /^Product name is required for item (\d+)|^Product name for item (\d+) must be (?:English|translated)/i.exec(message)
  if (match) fields.push(`items.${Number(match[1] ?? match[2]) - 1}.product_name`)
  match = /^(Buyer|Seller) (legal name|address|contact|phone|email|registration details)(?: is required| must be)/i.exec(message)
  if (match) fields.push(`${match[1].toLowerCase()}.${{ "legal name": "legal_name", "registration details": "registration_details" }[match[2].toLowerCase()] ?? match[2].toLowerCase()}`)
  match = /^(Incoterms and named place|Payment terms|Currency|Product family|Country of origin|Shipment reference|At least one line item)\b/i.exec(message)
  if (match) {
    const key = { "incoterms and named place": "incoterms", "payment terms": "payment_terms",
      currency: "currency", "product family": "product_family", "country of origin": "country_of_origin",
      "shipment reference": "shipment_reference", "at least one line item": "items.0.product_name" }[match[1].toLowerCase()]
    if (key) fields.push(key)
  }
  match = /^(?:Quantity unit|Price basis|Discount|Promotion quantity|Promotion rule|Shipped quantity) (?:for |of )?(?:item )?(\d+)?/i.exec(message)
  if (match?.[1]) {
    const key = /quantity unit/i.test(message) ? "unit" : /price basis/i.test(message) ? "price_basis" : /discount/i.test(message) ? "discount_percent" : /promotion rule/i.test(message) ? "promotion" : "quantity"
    fields.push(`items.${Number(match[1]) - 1}.${key}`)
  }
  match = /^PI bank detail required: (.+)$/i.exec(message)
  if (match) return { message: `설정의 계좌 ${LABELS[match[1]] ?? match[1]} 정보를 입력하세요.`, fields: [], settings: "bank" }
  if (/^Issuing company name is not configured$/i.test(message) || /must be the issuing company/i.test(message)) {
    const role = /buyer/i.test(message) || kind === "PO" ? "buyer" : "seller"
    const path = `${role}.legal_name`
    return { message: `${role === "buyer" ? "구매자" : "판매자"} 회사명이 발행 회사와 일치하도록 확인하세요.`, fields: validPath(draft, path) ? [path] : [], settings: "company" }
  }
  if (/currency rounding rule/i.test(message)) return { message: "설정에서 통화별 반올림 규칙을 확인하세요.", fields: [], settings: "company" }
  match = /^Price basis for (.+)$/i.exec(message)
  if (match) {
    const index = matchProduct(`for ${match[1]}`, draft)
    if (index !== null) fields.push(`items.${index}.price_basis`)
  }
  match = /^(?:Capacity|Promotion|Product Code|Price Source) for item (\d+) must be translated into English$/i.exec(message)
  if (match) {
    const key = /capacity/i.test(message) ? "capacity" : /promotion/i.test(message) ? "promotion" : /product code/i.test(message) ? "product_code" : "unit_price"
    fields.push(`items.${Number(match[1]) - 1}.${key}`)
  }
  match = /^(Incoterms|Remarks|Ship To|Bill To|Country Of Origin|Document Number|Shipment Reference|Actual Package Count|Hs Code) must be translated into English$/i.exec(message)
  if (match) {
    const key = { incoterms: "incoterms", remarks: "remarks", "ship to": "ship_to", "bill to": "bill_to", "country of origin": "country_of_origin",
      "document number": "document_number", "shipment reference": "shipment_reference", "actual package count": "actual_package_count", "hs code": "hs_code" }[match[1].toLowerCase()]
    if (key) fields.push(key)
  }
  match = /^Package (\d+) (package_type|dimensions|shipping_marks) must be translated into English$/i.exec(message)
  if (match) fields.push(`packages.${Number(match[1]) - 1}.${match[2]}`)
  match = /^Price basis (.+) does not match quantity unit (.+) for (.+)$/i.exec(message)
  if (match) {
    const index = matchProduct(`for ${match[3]}`, draft)
    if (index !== null) fields.push(`items.${index}.price_basis`, `items.${index}.unit`)
  }
  if (/confirm discount percentage/i.test(message)) {
    const index = matchProduct(message, draft)
    if (index !== null) fields.push(`items.${index}.discount_percent`)
  }
  if (/price basis .* does not match quantity unit/i.test(message)) {
    const index = matchProduct(message, draft)
    if (index !== null) fields.push(`items.${index}.price_basis`, `items.${index}.unit`)
  }
  if (/promotion quantity mismatch|shipped quantity must equal/i.test(message)) {
    const index = matchProduct(message, draft)
    if (index !== null) fields.push(`items.${index}.quantity`, `items.${index}.paid_quantity`, `items.${index}.free_quantity`)
  }
  if (/promotion rule .* must be confirmed/i.test(message)) {
    const index = matchProduct(message, draft)
    if (index !== null) fields.push(`items.${index}.promotion`, `items.${index}.free_quantity`)
  }
  if (/sample \d+: confirm/i.test(message)) {
    const index = Number(/sample (\d+)/i.exec(message)?.[1] ?? 1) - 1
    fields.push(`items.${index}.product_name`, `items.${index}.quantity`, `items.${index}.unit`, `items.${index}.unit_price`)
  }
  if (/required|must be/i.test(message)) {
    match = /(?:for|item) (\d+)/i.exec(message)
    if (match && /(?:unit|quantity|discount|price basis)/i.test(message)) {
      const key = /unit/i.test(message) ? "unit" : /discount/i.test(message) ? "discount_percent" : /price basis/i.test(message) ? "price_basis" : "quantity"
      fields.push(`items.${Number(match[1]) - 1}.${key}`)
    }
  }
  const valid = [...new Set(fields)].filter((path) => validPath(draft, path))
  if (valid.length) {
    const labels = valid.map((path) => fieldLabel(path, draft)).join(", ")
    const entering = valid.some((path) => !String(readPath(draft, path) ?? "").trim())
    return { message: `${labels} 항목${entering ? "의 값을 입력하세요" : "을 수정하세요"}.`, fields: valid }
  }
  if (/actual package count and weights/i.test(message)) return { message: "실제 포장 수와 중량 항목을 확인하세요.", fields: ["actual_package_count", "declared_net_weight_kg", "declared_gross_weight_kg"].filter((path) => validPath(draft, path)) }
  if (/^Confirm packing totals before final review$/i.test(message)) return { message: "포장 합계를 먼저 확인하고 승인하세요.", fields: [], packing: true }
  if (/package counts use different package types/i.test(message)) return { message: "포장 종류가 서로 다릅니다. 포장별 합계를 따로 확인하세요.", fields: [], packing: true }
  if (/PI import/i.test(message)) return { message: "원본 PI와 품목별 수량·단가·금액을 대조하세요.", fields: [], source: true }
  if (/^Document type must/i.test(message)) return { message: "문서 종류를 다시 선택하세요.", fields: [] }
  if (/^Currency rounding rule/i.test(message)) return { message: "설정에서 통화별 반올림 규칙을 확인하세요.", fields: [], settings: "company" }
  if (/english|translated into english/i.test(message)) return { message: "영문으로 입력된 항목을 수정하세요.", fields: [] }
  if (/^Confirm conflicting|^Resolve conflicting/i.test(message)) return { message: "원문과 입력값이 다른 항목을 확인하고 수정하세요.", fields: [] }
  return { message: "문서 입력 항목을 확인하고 수정하세요.", fields: [] }
}

function fieldLabel(path, draft) {
  const [first, index, key] = path.split(".")
  if (first === "buyer" || first === "seller") return `${first === "buyer" ? "구매자" : "판매자"} · ${LABELS[index] ?? index}`
  if ((first === "items" || first === "packages") && key) {
    const name = first === "items" ? draft.items?.[Number(index)]?.product_name : null
    return `${first === "items" ? `품목 ${Number(index) + 1}${name ? ` (${name})` : ""}` : `포장 ${Number(index) + 1}`} · ${LABELS[key] ?? key}`
  }
  return LABELS[first] ?? first
}

function inputType(path) {
  return /(?:quantity|price|percent|weight|volume|package_count|container_count|total_quantity)/.test(path) ? "number" : "text"
}

export default function MissingFieldsDialog({ open, kind, draft, missing = [], issues = [], packingIssues = [], busy, dirty, onChange, onSave, onOpenStep }) {
  const [selected, setSelected] = useState(null)
  const firstField = useRef(null)
  const entries = useMemo(() => {
    const rows = [
      ...missing.map((path) => ({ key: `missing:${path}`, raw: path, missing: true })),
      ...issues.map((issue, index) => ({ key: `issue:${index}:${issue?.message ?? issue}`, raw: issue })),
      ...packingIssues.map((issue, index) => ({ key: `packing:${index}:${issue}`, raw: `Packing: ${issue}` })),
    ]
    return rows.map((row) => {
      const rawMessage = String(typeof row.raw === "string" ? row.raw : row.raw?.message ?? "").trim()
      if ((row.missing && row.raw === "document_number")
          || /document number/i.test(rawMessage.replace(/_/g, " "))) return null
      if (/^Issuing company name is not configured$/i.test(rawMessage)) {
        return { ...row, message: "설정에서 당사 영문 회사명을 등록하세요.", fields: [], settings: "company" }
      }
      const issuerPath = kind === "PO" ? "buyer.legal_name" : "seller.legal_name"
      let detail = row.missing
        ? row.raw === "items" ? { message: "품목 항목을 추가하세요.", fields: [], step: kind === "PL" ? "packing" : kind === "CI" ? null : "items", source: kind === "CI" }
          : { message: `${fieldLabel(row.raw, draft)} 항목${String(readPath(draft, row.raw) ?? "").trim() ? "을 수정하세요" : "의 값을 입력하세요"}.`, fields: validPath(draft, row.raw) ? [row.raw] : [] }
        : issueDetails(row.raw, draft, kind)
      if (row.raw === issuerPath || detail.fields?.includes(issuerPath)) {
        const fields = (detail.fields ?? []).filter((path) => path !== issuerPath)
        detail = fields.length ? { ...detail, fields }
          : { message: `${kind === "PO" ? "구매자" : "판매자"} 회사명이 설정의 당사 회사명과 일치하지 않습니다. 회사 설정을 확인한 뒤 다시 저장하세요.`, fields: [], settings: "company" }
      }
      return { ...row, ...detail }
    }).filter(Boolean).filter((entry, index, all) => {
      if (!entry.fields?.length) return true
      const signature = JSON.stringify([entry.message, entry.fields])
      return all.findIndex((candidate) => JSON.stringify([candidate.message, candidate.fields]) === signature) === index
    })
  }, [draft, issues, kind, missing, packingIssues])
  const active = entries.find((entry) => entry.key === selected)
  const canShow = open && entries.length > 0

  useEffect(() => { if (active?.fields?.length) firstField.current?.focus() }, [active?.key])

  if (!canShow) return null
  return <section className="document-issue-editor" aria-label={`${kind} 오류 항목 수정`}>
    <h3>입력 오류</h3>
    <p className="section-note">오류 항목을 선택하면 관련 입력란이 아래에 열립니다. 값을 수정한 뒤 저장하세요.</p>
    <ul className="document-issue-list" role="list">
      {entries.map((entry) => <li key={entry.key}><button type="button" className="document-issue-link" aria-expanded={selected === entry.key}
        onClick={() => setSelected(selected === entry.key ? null : entry.key)}>{entry.message}</button></li>)}
    </ul>
    {active && <div className="document-issue-fields" aria-live="polite">
      <div className="panel-head"><h4>항목 수정·입력</h4><button className="btn" type="button" onClick={() => setSelected(null)}>닫기</button></div>
      {active.fields.length ? <div className="settings-fields">{active.fields.map((path, index) => {
        const value = readPath(draft, path) ?? ""
        const label = fieldLabel(path, draft)
        const multiline = /(?:address|remarks|ship_to|bill_to|terms|promotion|shipping_marks)/.test(path)
        const Control = multiline ? "textarea" : "input"
        const pricePath = path.match(/^(items\.\d+)\.unit_price$/)
        return <div className={`field${multiline ? " full" : ""}`} key={path}>
          <label htmlFor={`issue-field-${path.replaceAll(".", "-")}`}>{label}</label>
          <Control ref={index === 0 ? firstField : undefined} id={`issue-field-${path.replaceAll(".", "-")}`} type={multiline ? undefined : inputType(path)} value={value}
            min={inputType(path) === "number" ? "0" : undefined} step={inputType(path) === "number" ? "any" : undefined} maxLength={4000}
            onChange={(event) => onChange(path, event.target.value)} />
          {pricePath && <label className="missing-fields-confirm"><input type="checkbox" checked={Boolean(readPath(draft, `${pricePath[1]}.confirm_price_override`))}
            onChange={(event) => onChange(`${pricePath[1]}.confirm_price_override`, event.target.checked)} /> 단가표 대신 입력한 단가 사용</label>}
        </div>
      })}</div> : <>
        <p className="section-note">
          {active.settings ? <>관련 값은 <Link to={`/settings${active.settings === "bank" ? "?section=bank" : ""}`}>설정 화면</Link>에서 수정한 뒤 문서에서 다시 저장하세요.</>
            : active.packing ? <>포장 합계 화면에서 값을 확인하고 승인하세요. <a href="#packing-review">포장 합계 확인으로 이동</a></>
              : active.source ? "원본 PI와 선택한 CI 내용을 대조해 주세요. 원본 문서는 해당 PI에서 수정하세요." : active.step ? "품목 입력 단계에서 품목을 추가하세요. 기존 문서 작성 규칙은 그대로 적용됩니다." : "관련 문서 정보와 설정을 확인해 주세요."}
        </p>
        {active.step && onOpenStep && <button className="btn" type="button" disabled={busy} onClick={() => { onOpenStep(active.step); setSelected(null) }}>관련 입력 단계로 이동</button>}
      </>}
      {active.catalogMatch && active.confirmPath && <label className="missing-fields-confirm">
        <input type="checkbox" checked={Boolean(readPath(draft, active.confirmPath))}
          onChange={(event) => onChange(active.confirmPath, event.target.checked)} /> 등록 품목과 달라도 직접 입력한 품목 정보를 사용
      </label>}
      {active.fields.length > 0 && <p className="section-note" role="status">
        {dirty ? active.catalogMatch && readPath(draft, active.confirmPath)
          ? "수기 품목 정보를 사용하도록 확인했습니다. 저장하면 단가·필수 항목 등 나머지 기준을 다시 확인합니다."
          : "변경사항을 저장하면 서버가 다시 검증합니다. 입력값이 조건을 충족하면 해당 오류가 사라집니다." : active.catalogMatch
          ? "등록 품목과 다르게 사용하려면 위 확인란을 선택한 뒤 저장하세요."
          : "현재 값은 이미 저장되어 있습니다. 값을 바꾸면 저장 버튼이 활성화됩니다."}
      </p>}
      <div className="form-actions"><button className="btn blue" type="button" disabled={busy || !dirty || !active.fields.length} onClick={onSave}>{busy ? "저장 중…" : "변경사항 저장"}</button></div>
    </div>}
  </section>
}
