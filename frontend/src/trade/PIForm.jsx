import { useId } from "react"
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

export default function PIForm({ draft, setDraft, missing = [], disabled = false, onDirty }) {
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
  return <fieldset className="settings-form" disabled={disabled}>
    <div className="settings-fields">
      <div className="field"><label htmlFor="pi-family">상품군</label><select id="pi-family" value={draft.product_family ?? ""} aria-invalid={missing.includes("product_family") || undefined} onChange={(event) => change("product_family", event.target.value)}>
        <option value="" disabled>상품군을 선택해 주세요</option>
        {[["other","기타"],["cosmetics","화장품"],["polysilicon","폴리실리콘"],["wafer","웨이퍼"],["solar_cell","태양전지"],["solar_module","태양광 모듈"]].map(([value,label]) => <option key={value} value={value}>{label}</option>)}
      </select></div>
      <DocumentField label="PI 문서번호" value={draft.document_number} error={missing.includes("document_number")} onChange={(value) => change("document_number", value)} />
      <DocumentField label="통화" value={draft.currency} maxLength={3} pattern="[A-Z]{3}" onChange={(value) => change("currency", value.toUpperCase())} />
      <DocumentField label="납품 조건 (Incoterms·장소)" value={draft.incoterms} error={missing.includes("incoterms")} onChange={(value) => change("incoterms", value)} />
      <DocumentField label="지급 조건" value={draft.payment_terms} error={missing.includes("payment_terms")} onChange={(value) => change("payment_terms", value)} />
    </div>
    {[["buyer","구매자"],["seller","판매자"]].map(([role,title]) => <section key={role}>
      <h2 className="editor-section-title">{title}</h2>
      <div className="settings-fields">
        {[["legal_name","회사명"],["address","주소"],["contact","담당자"],["phone","전화"],["email","이메일"],["registration_details","등록 정보"]].map(([key,label]) =>
          <DocumentField key={key} label={`${title} ${label}`} value={draft[role]?.[key]} onChange={(value) => party(role,key,value)} error={missing.includes(`${role}.${key}`)} />)}
      </div>
    </section>)}
    <p className="section-note">발행 회사·통화별 계좌와 비어 있는 판매자 기본값은 <Link to="/settings">회사 설정</Link>에서 읽습니다. 추출된 당사자 정보도 위에서 수정할 수 있으며 서버가 적용한 내용은 저장 후 확인하세요.</p>
    <h2 className="editor-section-title">품목</h2>
    <div className="document-items">
      {draft.items.map((row,index) => <section className="document-item" key={row.rowId} aria-label={`품목 ${index+1}`}>
        <div className="panel-head"><h3 className="section-title">품목 {index+1}</h3><button type="button" className="btn" onClick={() => change("items", draft.items.filter((_,i) => i !== index))}>삭제</button></div>
        <div className="settings-fields">
          {[['product_name','품목명'],['product_code','상품 코드'],['capacity','용량·규격'],['quantity','유상 수량'],['free_quantity','무상 수량 (선택)'],['unit','수량 단위'],['unit_price','단가 (비우면 단가표)'],['price_basis','가격 기준'],['discount_percent','할인율 (%)'],['promotion','프로모션 (선택)']].map(([key,label]) =>
            <DocumentField key={key} label={label} value={row[key]} onChange={(value) => item(index,key,value)}
              disabled={(row.is_sample && ['free_quantity','discount_percent','promotion'].includes(key)) || (key === 'free_quantity' && Boolean(row.promotion))}
              placeholder={key === 'promotion' ? '예: 2+1 (무상 수량은 서버에서 계산)' : undefined}
              error={missing.includes(`items.${index}.${key}`)} inputMode={['quantity','paid_quantity','free_quantity','unit_price','discount_percent'].includes(key) ? 'decimal' : undefined} />)}
        </div>
        <div className="editor-checks">
          <label><input type="checkbox" checked={row.is_sample ?? false} onChange={(event) => item(index,"is_sample",event.target.checked)} /> 샘플 품목 (0원 포함)</label>
          <label><input type="checkbox" checked={row.confirm_price_override ?? false} onChange={(event) => item(index,"confirm_price_override",event.target.checked)} /> 단가표와 다른 거래 단가를 직접 확인했습니다</label>
        </div>
        <p className="section-note">상품·통화·거래처·단위를 바꾸면 단가 확인이 해제됩니다. 직접 입력한 단가(0원 포함)를 사용할 때는 확인을 선택하세요. 선택하지 않으면 서버가 단가표에서 다시 확인합니다. 프로모션 무상 수량은 서버가 계산합니다. 샘플은 독립 수량·단가를 사용하고 할인·무상 수량·프로모션은 적용하지 않습니다.</p>
      </section>)}
    </div>
    <button type="button" className="btn" disabled={draft.items.length >= 500} onClick={() => change("items", [...draft.items,newPIItem()])}>＋ 품목 추가</button>
    <div className="settings-fields">
      <DocumentField label="배송지" value={draft.ship_to} multiline rows={2} onChange={(value) => change("ship_to",value)} />
      <DocumentField label="청구지" value={draft.bill_to} multiline rows={2} onChange={(value) => change("bill_to",value)} />
      <DocumentField label="비고" value={draft.remarks} multiline rows={3} onChange={(value) => change("remarks",value)} />
    </div>
  </fieldset>
}
