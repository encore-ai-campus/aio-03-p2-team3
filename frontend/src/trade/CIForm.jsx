import { useId } from "react"

const fields = [["document_number","CI 문서번호"],["shipment_reference","선적 참조"],["country_of_origin","원산지"],
  ["incoterms","납품 조건"],["ship_to","배송지"],["bill_to","청구지"],["remarks","비고"]]

export default function CIForm({ draft, setDraft, onDirty, disabled, missing = [], onlyMissing = false, standalone = false }) {
  const prefix = useId()
  return <fieldset className="settings-form" disabled={disabled}><div className="settings-fields">
    {fields.filter(([key]) => !onlyMissing || missing.includes(key)).map(([key,label]) => <div className="field" key={key}>
      <label htmlFor={`${prefix}-${key}`}>{label}</label><input id={`${prefix}-${key}`} value={draft[key] ?? ""} maxLength={4000}
        aria-invalid={missing.includes(key) || undefined} onChange={(event) => {
          onDirty(); setDraft((previous) => ({ ...previous, [key]: event.target.value }))
        }} />
    </div>)}
  </div>{!standalone && <p className="section-note">당사자·품목·수량·통화·거래가격·FOC는 선택한 PI 버전에서 가져옵니다. 미입력 납품 조건·배송지·청구지·비고는 서버가 원본에서 가져올 수 있습니다.</p>}</fieldset>
}
