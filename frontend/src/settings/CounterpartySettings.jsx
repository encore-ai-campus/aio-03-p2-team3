import { useState } from "react"
import SettingsForm, { Field } from "./SettingsForm"

export default function CounterpartySettings({ data, save, saving, clearStatus, ...status }) {
  const [selected, setSelected] = useState("")
  const party = data.counterparties.find((row) => row.company_key === selected) ?? {}
  return (
    <>
      <div className="record-picker">
        <label htmlFor="counterparty-picker">저장된 거래처</label>
          <select id="counterparty-picker" value={selected} onChange={(event) => {
            clearStatus()
            setSelected(event.target.value)
          }} disabled={saving}>
            <option value="">새 거래처</option>
            {data.counterparties.map((row) => <option key={row.company_key} value={row.company_key}>{row.legal_name}</option>)}
          </select>
      </div>
      <p className="section-note">같은 회사명은 기존 정보를 갱신합니다. 회사명을 바꾸면 별도 거래처로 저장됩니다.</p>
      <SettingsForm key={selected} {...status} saving={saving} onSubmit={(values) => save("/counterparties", {
        ...values, aliases: values.aliases.split("\n").map((value) => value.trim()).filter(Boolean),
      })}>
        <Field label="거래처 회사명" name="legal_name" value={party.legal_name} required maxLength={200} />
        <Field label="담당자" name="contact" value={party.contact} />
        <Field label="이메일" name="email" type="email" value={party.email} />
        <Field label="전화번호" name="phone" type="tel" value={party.phone} />
        <Field label="주소" name="address" value={party.address} multiline rows={2} />
        <Field label="별칭 (한 줄에 하나, 최대 20개)" name="aliases" value={party.aliases?.join("\n")} multiline rows={3} />
        <Field label="등록 정보" name="registration_details" value={party.registration_details} multiline rows={2} />
        <Field label="기본 배송지" name="default_ship_to" value={party.default_ship_to} multiline rows={2} />
        <Field label="배송지 전화번호" name="ship_to_phone" value={party.ship_to_phone} type="tel" />
      </SettingsForm>
    </>
  )
}
