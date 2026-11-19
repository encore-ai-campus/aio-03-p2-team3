import { useEffect, useState } from "react"
import { apiFetch } from "../api"
import { KNOWLEDGE_ROOT } from "./upload.js"

export default function CounterpartyLink({ documentId, current, token, onChanged }) {
  const [counterparties, setCounterparties] = useState(null)
  const [value, setValue] = useState(current ?? "")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    apiFetch(`${KNOWLEDGE_ROOT}/counterparties`, { token, signal: controller.signal })
      .then(setCounterparties).catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message)
      })
    return () => controller.abort()
  }, [token])

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      await apiFetch(`${KNOWLEDGE_ROOT}/${documentId}/counterparty`, {
        token, method: "PUT", body: { counterparty_id: value === "" ? null : Number(value) },
      })
      onChanged()
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }

  return <form onSubmit={save} className="knowledge-actions" aria-label="계약서의 거래처 연결">
    <label className="field">계약 거래처
      <select aria-label="계약 거래처" value={value} disabled={!counterparties || busy} onChange={(event) => setValue(event.target.value)}>
        <option value="">연결 없음</option>
        {(counterparties || []).map((party) => <option key={party.id} value={party.id}>
          {party.legal_name}{party.email ? ` · ${party.email}` : ""}
        </option>)}
      </select>
    </label>
    <button className="btn" type="submit" disabled={!counterparties || busy || String(value) === String(current ?? "")}>거래처 연결 저장</button>
    {error && <p role="alert">{error}</p>}
  </form>
}
