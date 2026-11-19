import { useEffect, useMemo, useRef } from "react"
import { Link } from "react-router-dom"

import { fieldLabel, LABELS } from "./fieldLabel"

function readPath(value, path) {
  return path.split(".").reduce((current, key) => current?.[key], value)
}

function validPath(value, path) {
  const parts = path.split(".")
  const last = parts.pop()
  const parent = parts.length ? readPath(value, parts.join(".")) : value
  return Boolean(parent && typeof parent === "object" && (last in parent || LABELS[last]))
}

export function updateMissingField(value, path, nextValue) {
  const parts = path.split(".")
  const copy = structuredClone(value)
  let target = copy
  for (const key of parts.slice(0, -1)) target = target[key]
  target[parts.at(-1)] = nextValue
  const itemIndex = parts[0] === "items" ? Number(parts[1]) : -1
  if (itemIndex >= 0 && parts.at(-1) === "quantity") target.paid_quantity = nextValue
  return copy
}

function packingIssuePaths(issues) {
  const paths = []
  for (const raw of issues ?? []) {
    const message = String(typeof raw === "string" ? raw : raw?.message ?? "").replace(/^Packing:\s*/i, "")
    let match = /^Packing row (\d+): quantity and unit must be confirmed$/i.exec(message)
    if (match) paths.push(`items.${Number(match[1]) - 1}.quantity`, `items.${Number(match[1]) - 1}.unit`)
    match = /^Packing row (\d+): net weight exceeds gross weight$/i.exec(message)
    if (match) paths.push(`items.${Number(match[1]) - 1}.net_weight_kg`, `items.${Number(match[1]) - 1}.gross_weight_kg`)
    match = /^Packing row (\d+): (package count|net weight|gross weight|CBM) is invalid$/i.exec(message)
    if (match) {
      const field = { "package count": "package_count", "net weight": "net_weight_kg",
        "gross weight": "gross_weight_kg", cbm: "volume_cbm" }[match[2].toLowerCase()]
      paths.push(`items.${Number(match[1]) - 1}.${field}`)
    }
    match = /^Source (package count|net weight \(kg\)|gross weight \(kg\)|volume \(CBM\)|quantity) total is invalid$/i.exec(message)
    if (match) {
      const field = { "package count": "actual_package_count", "net weight (kg)": "declared_net_weight_kg",
        "gross weight (kg)": "declared_gross_weight_kg", "volume (cbm)": "declared_volume_cbm",
        quantity: "declared_total_quantity" }[match[1].toLowerCase()]
      paths.push(field)
    }
    if (/^Container count must be a non-negative whole number$/i.test(message)) paths.push("container_count")
    if (/^Source total quantity has conflicting units/i.test(message)) paths.push("declared_total_quantity_unit")
  }
  return paths
}

function resolvedPaths(missing, issues, draft) {
  const paths = []
  for (const raw of [...(missing ?? []), ...packingIssuePaths(issues)]) {
    const path = String(raw)
    if (/^(buyer|seller)\.[a-z_]+$|^(items|packages)\.\d+\.[a-z_]+$|^[a-z_]+$/.test(path) && validPath(draft, path)) {
      paths.push(path)
      continue
    }
    const priceMessage = /(?:catalog price|transaction-specific price).*? for (.+?)(?:;|\.|$)/i.exec(path)
    if (priceMessage) {
      const index = (draft.items ?? []).findIndex((item) => item.product_name?.toLowerCase().includes(priceMessage[1].trim().toLowerCase()))
      if (index >= 0) paths.push(`items.${index}.unit_price`)
    }
  }
  return [...new Set(paths)]
}

export default function MissingFieldsDialog({ open, kind, draft, missing, issues, busy, dirty, onChange, onSave, onClose }) {
  const ref = useRef(null)
  const paths = useMemo(() => resolvedPaths(missing, issues, draft), [missing, issues, draft])

  useEffect(() => {
    const dialog = ref.current
    if (open && dialog && !dialog.open) dialog.showModal()
    else if (!open && dialog?.open) dialog.close()
  }, [open])

  return <dialog ref={ref} className="missing-fields-dialog" aria-labelledby="missing-fields-title" onCancel={(event) => { event.preventDefault(); onClose() }} onClose={onClose}>
    <div className="missing-fields-head"><div><p className="eyebrow">{kind} document</p><h2 id="missing-fields-title">누락 정보를 입력해 주세요</h2>
      <p>값을 입력한 뒤 저장하면 문서의 새 버전으로 반영됩니다.</p></div>
      <button className="missing-fields-close" type="button" onClick={onClose} aria-label="팝업 닫기">×</button></div>
    {paths.length ? <div className="missing-fields-form">
      {paths.map((path) => {
        const value = readPath(draft, path) ?? ""
        const label = fieldLabel(path)
        const numeric = /(?:quantity|price|percent|weight|volume|package_count|container_count|total_quantity)/.test(path)
        const multiline = /(?:address|remarks|ship_to|bill_to|terms)/.test(path)
        const Control = multiline ? "textarea" : "input"
        return <div className="field" key={path}><label htmlFor={`missing-${path.replaceAll(".", "-")}`}>{label}</label>
          <Control id={`missing-${path.replaceAll(".", "-")}`} value={value} maxLength={4000} inputMode={numeric ? "decimal" : undefined}
            aria-invalid={!String(value).trim() || undefined} onChange={(event) => onChange(path, event.target.value)} />
          {path.endsWith(".unit_price") && <label className="missing-fields-confirm"><input type="checkbox" checked={Boolean(readPath(draft, `${path.slice(0, path.lastIndexOf("."))}.confirm_price_override`))}
            onChange={(event) => onChange(`${path.slice(0, path.lastIndexOf("."))}.confirm_price_override`, event.target.checked)} /> 단가표 대신 입력한 단가 사용</label>}
        </div>
      })}
    </div> : <p className="missing-fields-empty">이 오류는 문서 입력값이 아니라 설정 정보 확인이 필요합니다. <Link to={`/settings${kind === "PI" ? "?section=bank" : ""}`} onClick={onClose}>설정 열기</Link></p>}
    <div className="missing-fields-actions"><button className="btn" type="button" disabled={busy} onClick={onClose}>닫기</button>
      <button className="btn blue" type="button" disabled={busy || !dirty || !paths.length} onClick={onSave}>{busy ? "저장 중…" : "저장하고 반영"}</button></div>
  </dialog>
}
