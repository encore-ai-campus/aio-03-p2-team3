import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { apiFetch } from "../api"

export default function FollowupNotice({ token }) {
  const [snapshot, setSnapshot] = useState(null)

  useEffect(() => {
    if (!token) return
    let request
    async function poll() {
      request?.abort()
      request = new AbortController()
      const { signal } = request
      try {
        const data = await apiFetch("/mail/followups?due_only=true", { token, signal })
        if (!signal.aborted) setSnapshot({ token, items: data.followups, more: Boolean(data.next_cursor) })
      } catch {
        // 열린 화면에서 다음 주기에 다시 확인한다.
      }
    }
    poll()
    const timer = window.setInterval(poll, 30000)
    window.addEventListener("focus", poll)
    window.addEventListener("mail-followups-changed", poll)
    return () => {
      request?.abort()
      window.clearInterval(timer)
      window.removeEventListener("focus", poll)
      window.removeEventListener("mail-followups-changed", poll)
    }
  }, [token])

  if (snapshot?.token !== token || !snapshot?.items.length) return null
  const [first] = snapshot.items
  return <aside className="followup-notice" aria-label="답장 대기 알림">
    <div role="status"><strong>기한까지 답장이 오지 않았습니다</strong>
      <span>{first.subject || "(제목 없음)"}{snapshot.items.length > 1 && ` 외 ${snapshot.items.length - 1}${snapshot.more ? "+" : ""}건`}</span></div>
    <Link to={`/inbox?thread=${encodeURIComponent(first.thread_id)}`}>메일 확인</Link>
    <Link to="/inbox?followups=1">후속 알림 관리</Link>
  </aside>
}
