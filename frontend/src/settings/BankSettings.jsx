import { useState } from "react"
import SettingsForm, { Field } from "./SettingsForm"

export default function BankSettings({ data, save, saving, clearStatus, ...status }) {
  const [currency, setCurrency] = useState(data.banks[0]?.currency ?? "USD")
  const bank = data.banks.find((row) => row.currency === currency) ?? {}
  return (
    <>
      <div className="record-picker">
        <label>계좌 통화
          <input form="bank-settings" name="currency" value={currency} disabled={saving} required pattern="[A-Z]{3}" maxLength={3}
            list="bank-currencies" onChange={(event) => {
              clearStatus()
              setCurrency(event.target.value.toUpperCase())
            }} />
        </label>
        <datalist id="bank-currencies">{Array.from(new Set(["USD", "KRW", "EUR", "JPY", "CNY", ...data.banks.map((row) => row.currency)]))
          .map((code) => <option key={code} value={code} />)}</datalist>
      </div>
      <p className="section-note">통화별 계좌를 저장합니다. 계좌 정보는 해당 통화의 PI에 적용됩니다.</p>
      <SettingsForm key={currency} id="bank-settings" {...status} saving={saving} onSubmit={({ currency: code, ...values }) => save(`/banks/${encodeURIComponent(code)}`, values)}>
        <Field label="수취인 (Beneficiary)" name="beneficiary" value={bank.beneficiary} required />
        <Field label="은행명" name="bank_name" value={bank.bank_name} required />
        <Field label="지점" name="branch" value={bank.branch} required />
        <Field label="SWIFT 코드" name="swift" value={bank.swift} required />
        <Field label="계좌번호" name="account_number" value={bank.account_number} required />
        <Field label="은행 주소" name="bank_address" value={bank.bank_address} required multiline rows={2} />
      </SettingsForm>
      <div className="saved-records" aria-label="등록 계좌 목록">
        {data.banks.map((row) => <button className="setting-row" key={row.currency} type="button" disabled={saving} onClick={() => {
          clearStatus()
          setCurrency(row.currency)
        }}>
          <b>{row.currency} · {row.bank_name}</b><span>{row.beneficiary}</span>
        </button>)}
      </div>
    </>
  )
}
