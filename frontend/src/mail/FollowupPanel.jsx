import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { apiFetch } from "../api"
import { FollowupResult } from "../agent/MailWorkResult"

export default function FollowupPanel({ token }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    apiFetch("/mail/followups", { token, signal: controller.signal }).then(setData).catch(failure => {
      if (failure.name !== "AbortError") setError(failure.message)
    })
    return () => controller.abort()
  }, [token])

  async function cancel(id) {
    setBusy(id)
    setError("")
    try {
      const saved = await apiFetch(`/mail/followups/${id}`, { method: "DELETE", token })
      setData(current => ({ ...current, followups: current.followups.map(item => item.id === saved.id ? saved : item) }))
      window.dispatchEvent(new Event("mail-followups-changed"))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(null)
    }
  }

  async function more() {
    setBusy("more")
    setError("")
    try {
      const next = await apiFetch(`/mail/followups?cursor=${data.next_cursor}`, { token })
      setData(current => ({ ...next, next_cursor: next.next_cursor, followups: [...current.followups, ...next.followups] }))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(null)
    }
  }

  const active = data?.followups.filter(item => ["pending", "due"].includes(item.status)) ?? []
  return <section className="followup-panel">
    <header><h2>메일 후속 알림</h2><Link to="/inbox">받은 메일로</Link></header>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">알림을 불러오는 중입니다.</p>}
    {data && <FollowupResult data={{ followups: data.followups }} />}
    {active.length > 0 && <div className="followup-cancel-list">{active.map(item => <button type="button"
      className="btn" key={item.id} disabled={busy !== null} onClick={() => cancel(item.id)}>
      {item.subject || "(제목 없음)"} 알림 취소
    </button>)}</div>}
    {data?.next_cursor && <button type="button" className="btn" disabled={busy !== null} onClick={more}>다음 알림 보기</button>}
  </section>
}
