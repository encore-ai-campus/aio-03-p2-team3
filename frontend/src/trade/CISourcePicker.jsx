import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { apiFetch } from "../api"
import { sourceLabel } from "./ci-input"

export default function CISourcePicker({ token, selected, disabled, onSelect }) {
  const [page, setPage] = useState({ items: [], next_cursor: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [reload, setReload] = useState(0)
  const request = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    setLoading(true)
    setError("")
    setPage({ items: [], next_cursor: null })
    apiFetch("/trade/ci/source-pis", { token, signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setPage(result)
    }).catch((failure) => { if (!controller.signal.aborted) setError(failure.message) })
      .finally(() => { if (request.current === controller) { request.current = null; setLoading(false) } })
    return () => { controller.abort(); request.current?.abort() }
  }, [token, reload])

  async function more() {
    if (request.current || !page.next_cursor) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true)
    setError("")
    try {
      const result = await apiFetch(`/trade/ci/source-pis?cursor=${encodeURIComponent(page.next_cursor)}`, { token, signal: controller.signal })
      if (!controller.signal.aborted) setPage((previous) => ({ ...result,
        items: [...previous.items, ...result.items.filter((row) => !previous.items.some((old) =>
          old.source_pi_id === row.source_pi_id && old.source_revision === row.source_revision))] }))
    } catch (failure) { if (!controller.signal.aborted) setError(failure.message) }
    finally { if (request.current === controller) { request.current = null; setLoading(false) } }
  }

  return <section aria-label="원본 PI 선택"><p className="pi-question-note">정보 보완 중인 PI도 선택할 수 있어요. 서버에 CI를 생성하려면 선택한 PI 버전의 승인이 필요합니다.</p>
    {error && <div className="form-error" role="alert">{error} <button className="btn" type="button" disabled={loading || disabled} onClick={() => setReload((value) => value + 1)}>목록 다시 읽기</button></div>}
    {!loading && !error && !page.items.length && <p>저장된 PI가 없습니다. <Link to="/trade/pi">PI 작성하기</Link></p>}
    {page.items.map((row) => <label className="ci-source-choice" key={`${row.source_pi_id}:${row.source_revision}`}>
      <input type="radio" name="source-pi" checked={selected?.source_pi_id === row.source_pi_id && selected?.source_revision === row.source_revision}
        disabled={disabled || loading} onChange={() => onSelect(row)} />
      <span><strong>{row.document_number || `PI ${row.source_pi_id}`} · 버전 {row.source_revision}</strong>
        <small>{row.currency || "통화 미입력"} {row.total ?? "합계 미확정"} · {sourceLabel(row)}</small>
        {!row.approved && row.current_revision !== row.source_revision && <small>현재 버전 {row.current_revision} 보완·승인 후 새 버전을 선택해 주세요.</small>}</span>
    </label>)}
    {loading && <p role="status">PI 목록을 읽는 중입니다…</p>}
    <div className="form-actions"><button className="btn" type="button" disabled={loading || disabled} onClick={() => setReload((value) => value + 1)}>목록 새로고침</button>
      {page.next_cursor && <button className="btn" type="button" disabled={loading || disabled} onClick={more}>이전 PI 버전 더 보기</button>}</div>
  </section>
}
