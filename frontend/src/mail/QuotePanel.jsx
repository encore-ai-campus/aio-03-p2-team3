import { useEffect, useRef, useState } from "react"
import { apiFetch, downloadFile } from "../api"

export default function QuotePanel({ candidate, token, onSaved }) {
  const { quote_id: id, document } = candidate
  const draft = document.draft
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const operation = useRef(null)
  useEffect(() => {
    setBusy(false)
    return () => { operation.current?.abort(); operation.current = null }
  }, [id, token])

  async function run(action) {
    if (operation.current) return
    const request = new AbortController(); operation.current = request
    setBusy(true); setError("")
    try { await action(request.signal) }
    catch (failure) { if (!request.signal.aborted) setError(failure.message) }
    finally {
      if (operation.current === request) operation.current = null
      if (!request.signal.aborted) setBusy(false)
    }
  }

  function save(event) {
    event.preventDefault()
    const prices = Object.fromEntries(new FormData(event.currentTarget))
    run(async (signal) => {
      await apiFetch(`/mail/quotes/${id}/prices`, { method: "POST", body: { prices }, token, signal })
      if (!signal.aborted) onSaved()
    })
  }

  return <details><summary>관련 국내 견적서 · {draft.quote_no}</summary>
    <p>거래처: {draft.customer_name} · 견적일: {draft.quote_date} · 유효기간: {draft.valid_until}</p>
    <p>공급자: {draft.supplier.company_name || "미입력"}</p>
    <ul>{draft.lines.map((line, index) => <li key={index}>
      {line.item_name} · {line.quantity}{line.unit || ""} · 단가 {line.unit_price ?? "미입력"}원 · 금액 {line.amount ?? "미확정"}원
    </li>)}</ul>
    {document.status === "needs_price" ? <form onSubmit={save} className="mail-prices">
      <p>빠진 단가를 입력하면 기존 견적 계산 규칙으로 합계를 확정합니다.</p>
      {draft.lines.map((line, index) => line.unit_price === null && <label key={index}>
        {line.item_name} 단가(원)<input name={String(index)} inputMode="numeric" pattern="[0-9]+" required maxLength={19} />
      </label>)}
      <button className="btn" disabled={busy}>단가 저장 · 합계 계산</button>
    </form> : <p>공급가액 {draft.supply_amount}원 · 부가세 {draft.vat}원 · 합계 {draft.total}원</p>}
    <button type="button" className="btn" disabled={busy} onClick={() => run((signal) => downloadFile({
      download_url: `/api/mail/quotes/${id}/preview.pdf`, filename: `${draft.quote_no}.pdf`,
    }, token, signal))}>견적서 PDF 확인</button>
    {error && <p role="alert">{error}</p>}
  </details>
}
