import { useId, useState } from "react"

const fields = [["document_number","CI 문서번호"],["shipment_reference","선적 참조"],["country_of_origin","원산지"],
  ["incoterms","납품 조건"],["ship_to","배송지"],["bill_to","청구지"],["remarks","비고"]]

export default function CIForm({ draft, setDraft, onDirty, disabled, missing = [], onlyMissing = false, standalone = false }) {
  const prefix = useId()
  return <fieldset className="settings-form" disabled={disabled}><div className="settings-fields">
    {fields.filter(([key]) => !onlyMissing || missing.includes(key)).map(([key,label]) => <div className="field" key={key}>
      <label htmlFor={`${prefix}-${key}`}>{label}</label><input id={`${prefix}-${key}`} value={draft[key] ?? ""} maxLength={4000}
        placeholder={key === "document_number" ? "승인·발급 시 자동 생성" : undefined} readOnly={key === "document_number"}
        aria-invalid={missing.includes(key) || undefined} onChange={(event) => {
          onDirty(); setDraft((previous) => ({ ...previous, [key]: event.target.value }))
        }} />
    </div>)}
  </div><p className="section-note">CI 문서번호는 최종 승인·발급 시 최신 순번으로 자동 생성됩니다.{!standalone && " 당사자·품목·수량·통화·거래가격·FOC는 선택한 PI 버전에서 가져옵니다. 미입력 납품 조건·배송지·청구지·비고는 서버가 원본에서 가져올 수 있습니다."}</p></fieldset>
}

export function CISummary({ source, original, draft, standalone = false }) {
  const [open, setOpen] = useState(false)
  const facts = standalone ? draft : original
  return <aside className="pi-summary" aria-label="작성 내용 요약"><button className="pi-summary-toggle" type="button" aria-expanded={open} aria-controls="ci-summary" onClick={() => setOpen(!open)}>작성 내용 {open ? "접기" : "보기"}</button>
    <div id="ci-summary" className={open ? "open" : ""}><h2>작성 중인 CI</h2><p className="pi-summary-number">{draft.document_number || "승인·발급 시 문서번호 자동 생성"}</p>
      <dl><div><dt>{standalone ? "작성 방식" : "원본 PI"}</dt><dd>{standalone ? "PI 없이 직접 작성" : source ? `${source.document_number || source.source_pi_id} · 버전 ${source.source_revision}` : "선택 필요"}</dd></div>
        <div><dt>구매자</dt><dd>{facts?.buyer?.legal_name || "—"}</dd></div><div><dt>판매자</dt><dd>{facts?.seller?.legal_name || "—"}</dd></div>
        <div><dt>{standalone ? "품목·유상/FOC 수량" : "원본 품목·유상/FOC 수량"}</dt><dd>{facts?.items?.map((row,index) => <div key={index}>{row.product_name} · {row.paid_quantity ?? row.quantity ?? "—"} / {row.free_quantity ?? "—"} {row.unit} · {row.unit_price ?? "미확정"}</div>) || "—"}</dd></div>
        <div><dt>선적 참조</dt><dd>{draft.shipment_reference || "미입력"}</dd></div></dl>
      {source && <div className="pi-summary-total"><span>선택한 PI 버전의 합계</span><strong>{source.currency} {source.total ?? "미확정"}</strong></div>}
      <p className="section-note">{standalone ? "금액과 판매 단가는 서버 저장 후 확인합니다." : "PI 승인 전에는 작성 준비만 가능합니다. 거래 사실은 선택한 승인 버전으로 고정됩니다."}</p>
    </div></aside>
}
