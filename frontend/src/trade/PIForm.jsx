import { Fragment, useId } from "react"
import { Link } from "react-router-dom"
import { newPIItem } from "./pi-input"

function DocumentField({ label, value, onChange, multiline = false, error, ...props }) {
  const id = useId()
  const Control = multiline ? "textarea" : "input"
  return <div className={`field${multiline ? " full" : ""}`}>
    <label htmlFor={id}>{label}</label>
    <Control id={id} value={value ?? ""} onChange={(event) => onChange(event.target.value)}
      aria-invalid={error || undefined} maxLength={4000} {...props} />
    {error && <span className="form-error">입력을 확인해 주세요</span>}
  </div>
}

export default function PIForm({ draft, setDraft, step, fields = null, settings, missing = [], disabled = false, onDirty, onShowAll }) {
  const wanted = (path) => fields === null || fields.includes(path)
  const invalid = (path) => missing.includes(path) || fields?.includes(path)
  function change(key, value) {
    onDirty()
    setDraft((previous) => ({ ...previous, [key]: value,
      ...(key === "currency" ? { items: previous.items.map((row) => ({ ...row, confirm_price_override: false })) } : {}) }))
  }
  function party(role, key, value) {
    onDirty()
    setDraft((previous) => ({ ...previous, [role]: { ...previous[role], [key]: value },
      ...(role === "buyer" && key === "legal_name" ? { items: previous.items.map((row) => ({ ...row, confirm_price_override: false })) } : {}) }))
  }
  function item(index, key, value) {
    onDirty()
    setDraft((previous) => ({ ...previous, items: previous.items.map((row, i) => i === index ? { ...row, [key]: value,
      ...(key === "quantity" ? { paid_quantity: value } : {}),
      ...(["product_name","product_code","capacity","unit"].includes(key) ? { confirm_price_override: false } : {}) } : row) }))
  }
  function chooseBuyer(key) {
    const selected = settings?.counterparties.find((row) => row.company_key === key)
    if (!selected) return
    onDirty()
    setDraft((previous) => ({ ...previous, buyer: Object.fromEntries(
      ["legal_name", "address", "contact", "phone", "email", "registration_details"].map((field) => [field, selected[field] ?? ""])),
      ship_to: selected.default_ship_to || previous.ship_to,
      items: previous.items.map((row) => ({ ...row, confirm_price_override: false })) }))
  }
  return <fieldset className="settings-form" disabled={disabled}>
    {(step === "buyer" || step === "seller") && <>
      {step === "buyer" && settings?.counterparties.length > 0 && <div className="record-picker">
        <label htmlFor="pi-buyer-picker">저장된 거래처에서 가져오기</label>
        <select id="pi-buyer-picker" value="" onChange={(event) => chooseBuyer(event.target.value)}>
          <option value="">거래처 선택</option>{settings.counterparties.map((row) => <option key={row.company_key} value={row.company_key}>{row.legal_name}</option>)}
        </select>
      </div>}
      {fields && draft[step]?.legal_name && <p className="pi-context">{draft[step].legal_name}</p>}
      <div className="settings-fields pi-party-fields">
        {[["legal_name","회사명 (영문)"],["address","주소 (영문)"]].filter(([key]) => wanted(`${step}.${key}`)).map(([key,label]) =>
          <DocumentField key={key} label={label} value={draft[step]?.[key]} onChange={(value) => party(step,key,value)}
            error={invalid(`${step}.${key}`) && !draft[step]?.[key]} multiline={key === "address"} rows={2} />)}
      </div>
      {!fields && <details className="pi-optional"><summary>담당자·연락처·등록 정보</summary><div className="settings-fields">
        {[["contact","담당자"],["phone","전화"],["email","이메일"],["registration_details","등록 정보"]].map(([key,label]) =>
          <DocumentField key={key} label={label} value={draft[step]?.[key]} onChange={(value) => party(step,key,value)} />)}
      </div></details>}
      {step === "seller" && <p className="section-note">발행 회사와 지급 계좌는 <Link to="/settings">회사 설정</Link>에서 관리합니다. 원문에서 가져온 판매자도 수정할 수 있어요.</p>}
    </>}
    {step === "terms" && <><div className="settings-fields">
      {wanted("product_family") &&
      <div className="field"><label htmlFor="pi-family">상품군</label><select id="pi-family" value={draft.product_family ?? ""} aria-invalid={missing.includes("product_family") || undefined} onChange={(event) => change("product_family", event.target.value)}>
        <option value="" disabled>상품군을 선택해 주세요</option>
        {[["other","기타"],["cosmetics","화장품"],["polysilicon","폴리실리콘"],["wafer","웨이퍼"],["solar_cell","태양전지"],["solar_module","태양광 모듈"]].map(([value,label]) => <option key={value} value={value}>{label}</option>)}
      </select></div>}
      {wanted("document_number") && <DocumentField label="PI 문서번호" value={draft.document_number} onChange={(value) => change("document_number", value)} placeholder="미확정이면 DRAFT" />}
      {wanted("currency") && <DocumentField label="통화" value={draft.currency} maxLength={3} pattern="[A-Z]{3}" onChange={(value) => change("currency", value.toUpperCase())} />}
      {wanted("incoterms") && <DocumentField label="납품 조건 (Incoterms·장소)" value={draft.incoterms} onChange={(value) => change("incoterms", value)} placeholder="예: FOB Busan" />}
      {wanted("payment_terms") && <DocumentField label="지급 조건" value={draft.payment_terms} onChange={(value) => change("payment_terms", value)} />}
    </div>
    {!fields && <details className="pi-optional"><summary>배송지·청구지·비고</summary><div className="settings-fields">
      <DocumentField label="배송지" value={draft.ship_to} multiline rows={2} onChange={(value) => change("ship_to",value)} />
      <DocumentField label="청구지" value={draft.bill_to} multiline rows={2} onChange={(value) => change("bill_to",value)} />
      <DocumentField label="비고" value={draft.remarks} multiline rows={3} onChange={(value) => change("remarks",value)} />
    </div></details>}</>}
    {step === "items" && <>
      <div className="pi-item-table"><table><caption className="sr-only">PI 품목 편집 · {draft.currency || "통화 미선택"}</caption>
        <thead><tr>{["품목명 (영문)","유상 수량","단위",`단가 (${draft.currency || "통화 미선택"})`,"가격 기준", ""].map((label,index) => <th key={index} scope="col">{label}</th>)}</tr></thead>
        <tbody>{draft.items.map((row,index) => <Fragment key={row.rowId}>
          <tr className="pi-item-main" aria-label={`품목 ${index+1}`}>
            {[["product_name","품목명 (영문)"],["quantity","유상 수량"],["unit","단위"],["unit_price",`단가 (${draft.currency || "통화 미선택"})`],["price_basis","가격 기준"]].map(([key,label]) => <td key={key}>
              {wanted(`items.${index}.${key}`) || fields?.includes("items") ? <DocumentField label={`${label} · 품목 ${index+1}`} value={row[key]}
                onChange={(value) => item(index,key,value)} inputMode={["quantity","unit_price"].includes(key) ? "decimal" : undefined}
                placeholder={key === "unit_price" ? "단가표" : key === "price_basis" ? "PCS" : undefined} /> : <span className="pi-filled"><small>{label}</small>{row[key] ?? "미입력"}</span>}
            </td>)}
            <td><button type="button" className="btn" aria-label={`품목 ${index+1} 삭제`} onClick={() => { onShowAll(); change("items", draft.items.filter((_,i) => i !== index)) }}>삭제</button></td>
          </tr>
          <tr className="pi-item-detail"><td colSpan={6}>
            <label className="pi-price-check"><input type="checkbox" aria-label={`품목 ${index+1} · 단가표 대신 입력한 단가 사용`} checked={row.confirm_price_override ?? false} onChange={(event) => item(index,"confirm_price_override",event.target.checked)} /> 단가표 대신 입력한 단가 사용</label>
            <details open={fields?.some((path) => path === `items.${index}.discount_percent`)}>
            <summary>품목 {index+1} 상세 · 규격·할인·샘플</summary>
            <div className="settings-fields">
              {[["product_code","상품 코드"],["capacity","용량·규격"],["discount_percent","할인율 (%)"],["free_quantity","무상 수량"],["promotion","프로모션"]].filter(([key]) => wanted(`items.${index}.${key}`) || fields?.includes("items")).map(([key,label]) =>
                <DocumentField key={key} label={`${label} · 품목 ${index+1}`} value={row[key]} onChange={(value) => item(index,key,value)}
                  disabled={(row.is_sample && ["free_quantity","discount_percent","promotion"].includes(key)) || (key === "free_quantity" && Boolean(row.promotion))}
                  placeholder={key === "promotion" ? "예: 2+1" : key === "price_basis" ? "예: PCS" : undefined}
                  inputMode={["free_quantity","discount_percent"].includes(key) ? "decimal" : undefined} />)}
            </div>
            <div className="editor-checks">
              <label><input type="checkbox" checked={row.is_sample ?? false} onChange={(event) => item(index,"is_sample",event.target.checked)} /> 샘플 품목 (0원 포함)</label>
            </div>
          </details></td></tr>
        </Fragment>)}</tbody>
      </table></div>
      {!draft.items.length && <p className="pi-context">품목을 하나 이상 추가해 주세요.</p>}
      <button type="button" className="btn pi-add-item" disabled={draft.items.length >= 500} onClick={() => { onShowAll(); change("items", [...draft.items,newPIItem()]) }}>품목 추가</button>
      <p className="section-note">가격 기준은 PCS·KG처럼 단가의 기준 단위입니다. 상품·통화·거래처·단위를 바꾸면 단가 확인이 해제됩니다. 무상 수량과 금액은 저장할 때 계산해요. 샘플에는 할인·무상 수량·프로모션을 적용하지 않습니다.</p>
    </>}
  </fieldset>
}
