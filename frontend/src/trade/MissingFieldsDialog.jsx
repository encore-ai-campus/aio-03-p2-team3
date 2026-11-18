import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"

const LABELS = {
  product_family: "상품군", document_number: "문서번호", document_type: "문서 종류", currency: "통화",
  incoterms: "납품 조건", payment_terms: "지급 조건", ship_to: "배송지", bill_to: "청구지",
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
    if (["unit_price", "product_name", "product_code", "capacity", "unit"].includes(parts.at(-1))) target.confirm_price_override = false
  }
  return copy
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
    if (index !== null) fields.push(`items.${index}.product_name`, `items.${index}.capacity`, `items.${index}.product_code`)
  }
  match = /^Product name is required for item (\d+)|^Product name for item (\d+) must be (?:English|translated)/i.exec(message)
  if (match) fields.push(`items.${Number(match[1] ?? match[2]) - 1}.product_name`)
  match = /^(Buyer|Seller) (legal name|address|contact|phone|email|registration details)(?: is required| must be)/i.exec(message)
  if (match) fields.push(`${match[1].toLowerCase()}.${{ "legal name": "legal_name", "registration details": "registration_details" }[match[2].toLowerCase()] ?? match[2].toLowerCase()}`)
  match = /^(Document number|Incoterms and named place|Payment terms|Currency|Product family|Country of origin|Shipment reference|At least one line item)\b/i.exec(message)
  if (match) {
    const key = { "document number": "document_number", "incoterms and named place": "incoterms", "payment terms": "payment_terms",
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
      const detail = row.missing
        ? row.raw === "items" ? { message: "품목 항목을 추가하세요.", fields: [], step: kind === "PL" ? "packing" : kind === "CI" ? null : "items", source: kind === "CI" }
          : { message: `${fieldLabel(row.raw, draft)} 항목${String(readPath(draft, row.raw) ?? "").trim() ? "을 수정하세요" : "의 값을 입력하세요"}.`, fields: validPath(draft, row.raw) ? [row.raw] : [] }
        : issueDetails(row.raw, draft, kind)
      return { ...row, ...detail }
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
        {active.step && onOpenStep && <button className="btn" type="button" disabled={busy} onClick={() => { onOpenStep(active.step); setSelected(null) }}>품목 입력으로 이동</button>}
      </>}
      <div className="form-actions"><button className="btn blue" type="button" disabled={busy || !dirty || !active.fields.length} onClick={onSave}>{busy ? "저장 중…" : "변경사항 저장"}</button></div>
    </div>}
  </section>
}
