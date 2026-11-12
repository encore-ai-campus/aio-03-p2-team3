import { useState } from "react"
import SettingsForm, { Field } from "./SettingsForm"

export default function PriceSettings({ role, data, save, saving, clearStatus, ...status }) {
  const [selected, setSelected] = useState("")
  const rows = data.prices.filter((row) => row.role === role)
  const price = rows.find((row) => String(row.id) === selected) ?? {}
  return (
    <>
      <div className="record-picker">
        <label htmlFor="price-picker">저장된 단가</label>
          <select id="price-picker" value={selected} disabled={saving} onChange={(event) => {
            clearStatus()
            setSelected(event.target.value)
          }}>
            <option value="">새 단가</option>
            {rows.map((row) => <option key={row.id} value={row.id}>{row.item_name} · {row.currency} {row.unit_price} · {row.party_key || "공통"}</option>)}
          </select>
      </div>
      <p className="section-note">같은 품목·통화·거래처의 단가를 갱신합니다. 판매와 구매 단가는 따로 저장됩니다.</p>
      <SettingsForm key={selected} {...status} saving={saving} onSubmit={(values) => save("/prices", { ...values, role })}>
        <Field label="품목명" name="item_name" value={price.item_name} required maxLength={200} />
        <Field label="상품 코드" name="product_code" value={price.product_code} maxLength={200} />
        <Field label="용량·규격" name="capacity" value={price.capacity} maxLength={200} />
        <Field label="통화 (영문 대문자 3자리)" name="currency" value={price.currency || "USD"} required pattern="[A-Z]{3}" maxLength={3} />
        <Field label="단가" name="unit_price" value={price.unit_price} required inputMode="decimal" placeholder="예: 8.50" maxLength={80} />
        <Field label="단위" name="unit" value={price.unit} maxLength={100} placeholder="예: PCS, KG" />
        <Field label="가격 기준" name="price_basis" value={price.price_basis} maxLength={100} placeholder="예: PCS" />
        <Field label="거래처 한정 (비우면 공통)" name="party_key" value={price.party_key} maxLength={200} list="price-parties" />
        <datalist id="price-parties">{data.counterparties.map((row) => <option key={row.company_key} value={row.legal_name} />)}</datalist>
      </SettingsForm>
      <div className="saved-records" aria-label="등록 단가 목록">
        {rows.length === 0 ? <p className="section-note">등록한 단가가 없습니다.</p> : rows.map((row) => (
          <button className="setting-row" key={row.id} type="button" disabled={saving} onClick={() => {
            clearStatus()
            setSelected(String(row.id))
          }}>
            <b>{row.item_name}</b><span>{row.currency} {row.unit_price} / {row.price_basis || row.unit || "단위 미입력"}<br />{row.party_key || "모든 거래처"}</span>
          </button>
        ))}
      </div>
    </>
  )
}
