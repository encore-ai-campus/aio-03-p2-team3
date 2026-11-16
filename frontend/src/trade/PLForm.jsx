import { Fragment, useId } from "react"
import { newPLItem, newPackage, PACKAGE_FIELDS } from "./pl-input"

const LABELS = { product_name: "품목명 (영문)", quantity: "수량", unit: "단위", package_type: "포장 종류", package_count: "포장 수",
  net_weight_kg: "순중량 (kg)", gross_weight_kg: "총중량 (kg)", dimensions: "치수", shipping_marks: "배송 표시",
  volume_cbm: "부피 (CBM)", product_code: "상품 코드", capacity: "용량·규격", source: "출처" }

function Field({ label, value, onChange, multiline = false, ...props }) {
  const id = useId()
  const Control = multiline ? "textarea" : "input"
  return <div className="field"><label htmlFor={id}>{label}</label><Control id={id} value={value ?? ""} maxLength={4000} onChange={(event) => onChange(event.target.value)} {...props} /></div>
}

export default function PLForm({ draft, setDraft, step, fields = null, settings, missing = [], disabled, onDirty, onShowAll }) {
  const wanted = (path) => fields === null || fields.includes(path)
  function change(key,value) { onDirty(); setDraft((previous) => ({ ...previous, [key]: value })) }
  function party(role,key,value) { onDirty(); setDraft((previous) => ({ ...previous, [role]: { ...previous[role], [key]: value } })) }
  function rowChange(list,index,key,value) {
    onDirty(); setDraft((previous) => ({ ...previous, [list]: previous[list].map((row,i) => i === index ? { ...row, [key]: value } : row) }))
  }
  function itemField(list,index,row,key) {
    const path = `${list}.${index}.${key}`
    return <Field key={key} label={`${LABELS[key]} · ${list === "items" ? "품목" : "포장"} ${index+1}`} value={row[key]}
      inputMode={["quantity","package_count","net_weight_kg","gross_weight_kg","volume_cbm"].includes(key) ? "decimal" : undefined}
      aria-invalid={missing.includes(path) || undefined} onChange={(value) => rowChange(list,index,key,value)} />
  }
  return <fieldset className="settings-form" disabled={disabled}>
    {["buyer","seller"].includes(step) && <>
      {step === "buyer" && settings?.counterparties.length > 0 && <div className="record-picker"><label htmlFor="pl-buyer-picker">저장된 거래처에서 가져오기</label>
        <select id="pl-buyer-picker" value="" onChange={(event) => {
          const selected = settings.counterparties.find((row) => row.company_key === event.target.value)
          if (selected) change("buyer", Object.fromEntries(["legal_name","address","contact","phone","email","registration_details"].map((key) => [key,selected[key] ?? ""])))
        }}><option value="">거래처 선택</option>{settings.counterparties.map((row) => <option value={row.company_key} key={row.company_key}>{row.legal_name}</option>)}</select></div>}
      {fields && draft[step]?.legal_name && <p className="pi-context">{draft[step].legal_name}</p>}
      <div className="settings-fields pi-party-fields">{[["legal_name","회사명 (영문)"],["address","주소 (영문)"]].filter(([key]) => wanted(`${step}.${key}`)).map(([key,label]) =>
        <Field key={key} label={label} value={draft[step]?.[key]} multiline={key === "address"} rows={2} aria-invalid={missing.includes(`${step}.${key}`) || undefined} onChange={(value) => party(step,key,value)} />)}</div>
      {!fields && <details className="pi-optional"><summary>담당자·연락처·등록 정보</summary><div className="settings-fields">{[["contact","담당자"],["phone","전화"],["email","이메일"],["registration_details","등록 정보"]].map(([key,label]) =>
        <Field key={key} label={label} value={draft[step]?.[key]} onChange={(value) => party(step,key,value)} />)}</div></details>}
    </>}
    {step === "packing" && <>
      <div className="pi-item-table pl-item-table"><table><caption className="sr-only">PL 품목·포장 편집</caption>
        <thead><tr>{["품목명 (영문)","수량","단위","포장 수","포장 종류", ""].map((label,index) => <th key={index} scope="col">{label}</th>)}</tr></thead>
        <tbody>{draft.items.map((row,index) => <Fragment key={row.rowId}>
          <tr className="pi-item-main">{["product_name","quantity","unit","package_count","package_type"].map((key) => <td key={key}>
            {wanted(`items.${index}.${key}`) || fields?.includes("items") ? itemField("items",index,row,key) : <span className="pi-filled"><small>{LABELS[key]}</small>{row[key] || "미입력"}</span>}</td>)}
            <td><button className="btn" type="button" aria-label={`품목 ${index+1} 삭제`} onClick={() => { onShowAll(); change("items",draft.items.filter((_,i) => i !== index)) }}>삭제</button></td></tr>
          <tr className="pi-item-detail"><td colSpan={6}><details open={fields?.some((path) => path.startsWith(`items.${index}.`) && !["product_name","quantity","unit","package_count","package_type"].some((key) => path.endsWith(`.${key}`)))}>
            <summary>품목 {index+1} 상세 · 중량·부피·규격</summary><div className="settings-fields">{["net_weight_kg","gross_weight_kg","volume_cbm","dimensions","shipping_marks","product_code","capacity","source"].filter((key) => wanted(`items.${index}.${key}`) || fields?.includes("items")).map((key) => itemField("items",index,row,key))}</div>
          </details></td></tr>
        </Fragment>)}</tbody></table></div>
      <button className="btn pi-add-item" type="button" disabled={draft.items.length >= 500} onClick={() => { onShowAll(); change("items",[...draft.items,newPLItem()]) }}>품목 추가</button>
      <details className="pi-optional" open={fields?.some((path) => path.startsWith("packages"))}><summary>별도 포장 행</summary>
        <p className="section-note">품목별 포장과 별도 포장 행은 각각 보존합니다. 어느 쪽을 합계에 사용할지는 서버 결과에서 확인해요.</p>
        {draft.packages.map((row,index) => <div className="pl-package" key={row.rowId}><h3>포장 {index+1}</h3><div className="settings-fields">{PACKAGE_FIELDS.map((key) => itemField("packages",index,row,key))}</div>
          <button className="btn" type="button" aria-label={`포장 ${index+1} 삭제`} onClick={() => { onShowAll(); change("packages",draft.packages.filter((_,i) => i !== index)) }}>포장 삭제</button></div>)}
        <button className="btn" type="button" disabled={draft.packages.length >= 500} onClick={() => { onShowAll(); change("packages",[...draft.packages,newPackage()]) }}>포장 행 추가</button>
      </details><p className="section-note">PCS·KG는 따로 입력해요. 중량·부피·합계는 저장 후 서버 결과로 확인합니다.</p>
    </>}
    {step === "terms" && <>
      <div className="settings-fields">
        {wanted("product_family") && <div className="field"><label htmlFor="pl-family">상품군</label><select id="pl-family" value={draft.product_family ?? ""} onChange={(event) => change("product_family",event.target.value)}><option value="" disabled>상품군을 선택해 주세요</option>
          {[["other","기타"],["cosmetics","화장품"],["polysilicon","폴리실리콘"],["wafer","웨이퍼"],["solar_cell","태양전지"],["solar_module","태양광 모듈"]].map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></div>}
        {[["document_number","PL 문서번호"],["shipment_reference","선적 참조"],["hs_code","HS 코드"],["incoterms","납품 조건"],
          ["actual_package_count","원본 포장 수"],["container_count","원본 컨테이너 표기"],["declared_net_weight_kg","원본 순중량 (kg)"],
          ["declared_gross_weight_kg","원본 총중량 (kg)"],["declared_volume_cbm","원본 부피 (CBM)"],["declared_total_quantity","원본 총수량"],["declared_total_quantity_unit","원본 수량 단위"]].filter(([key]) => wanted(key)).map(([key,label]) =>
          <Field key={key} label={label} value={draft[key]} aria-invalid={missing.includes(key) || undefined} onChange={(value) => change(key,value)} />)}
      </div>{!fields && <details className="pi-optional"><summary>배송지·청구지·비고</summary><div className="settings-fields">{[["ship_to","배송지"],["bill_to","청구지"],["remarks","비고"]].map(([key,label]) =>
        <Field key={key} label={label} value={draft[key]} multiline rows={2} onChange={(value) => change(key,value)} />)}</div></details>}
      <p className="section-note">컨테이너가 없는 선적은 비워도 됩니다. 원본 단위와 ‘2 x 40FT’ 같은 표기를 그대로 보존해요.</p>
    </>}
  </fieldset>
}
