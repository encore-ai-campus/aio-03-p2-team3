import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { apiFetch } from "../api"
import { useAuth } from "../useAuth"
import "./mailbox.css"
import QuotePanel from "./QuotePanel"

const STATUS = { processing: "처리 중", awaiting_approval: "답장 대기", sent: "보냄",
  error: "처리 오류", ignored: "초안 없음", needs_review: "확인 필요" }
const RESULTS = { sent: "메일을 보냈습니다.", already_sent: "이미 발송했거나 처리한 후보입니다.",
  failed_unknown: "발송 여부를 확인하지 못했습니다. Gmail 보낸편지함을 확인한 뒤 다시 승인해 주세요.",
  failed_auth: "Gmail 권한을 확인하고 다시 연결해 주세요.", failed: "발송에 실패했습니다. 연결과 문서를 확인해 주세요.",
  needs_input: "관련 문서의 필수 항목을 먼저 확인해 주세요.", needs_seal: "회사 직인을 먼저 등록해 주세요.",
  needs_price: "관련 국내 견적서에서 빠진 단가를 먼저 입력해 주세요.",
  needs_pi_source: "CI의 PI 원문 근거를 먼저 확인해 주세요.", document_changed: "문서가 변경됐습니다. 최신 내용을 다시 확인해 주세요." }
const date = (value) => value ? new Date(value).toLocaleString("ko-KR") : ""
const canSend = (candidate) => ["pending", "send_failed"].includes(candidate.status)
const NOTICE = { local_worker_key_forbidden: "개인 PC 실행 방식은 자동 분류를 지원하지 않습니다. 업무 메일로 확인 후 처리할 수 있습니다.",
  processing_interrupted: "AI 처리 중 서버가 재시작됐습니다. 저장된 내용을 확인한 뒤 다시 처리해 주세요.",
  connection_changed: "처리 중 Gmail 연결이 바뀌었습니다. 연결 상태를 확인해 주세요." }

export default function MailboxPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const [params, setParams] = useSearchParams()
  const selected = params.get("thread") || ""
  const [filter, setFilter] = useState("")
  const [query, setQuery] = useState("")
  const [cursor, setCursor] = useState(null)
  const [list, setList] = useState({ items: [], next_cursor: null })
  const [thread, setThread] = useState(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null)
  const [reload, setReload] = useState(0)
  const operation = useRef(null)
  const confirmation = useRef(null)

  useEffect(() => { if (preview) confirmation.current?.focus() }, [preview])

  useEffect(() => {
    let cancelled = false, timer, request
    setList({ items: [], next_cursor: null }); setLoading(true)
    async function read() {
      if (document.hidden) return
      clearTimeout(timer); request?.abort()
      const current = new AbortController(); request = current
      const search = new URLSearchParams()
      if (filter) search.set("status", filter)
      if (query) search.set("q", query)
      if (cursor) search.set("cursor", cursor)
      try {
        const data = await apiFetch(`/mail/threads?${search}`, { token, signal: current.signal })
        if (!cancelled && request === current) { setList(data); setError("") }
      } catch (failure) {
        if (!cancelled && request === current && failure.name !== "AbortError") setError(failure.message)
      } finally {
        if (!cancelled && request === current) { setLoading(false); timer = setTimeout(read, 30000) }
      }
    }
    read(); document.addEventListener("visibilitychange", read)
    return () => { cancelled = true; clearTimeout(timer); request?.abort(); document.removeEventListener("visibilitychange", read) }
  }, [token, filter, query, cursor, reload])

  useEffect(() => {
    let cancelled = false, timer, request
    setThread(null); setDetailError(""); setPreview(null)
    setDetailLoading(Boolean(selected))
    async function read() {
      if (!selected || document.hidden) return
      clearTimeout(timer); request?.abort()
      const current = new AbortController(); request = current
      try {
        const data = await apiFetch(`/mail/threads/${encodeURIComponent(selected)}`, { token, signal: current.signal })
        if (!cancelled && request === current) {
          setThread(data); setDetailError("")
          if (data.processing.some((item) => item.status === "processing")) timer = setTimeout(read, 5000)
        }
      } catch (failure) {
        if (!cancelled && request === current && failure.name !== "AbortError") setDetailError(failure.message)
      } finally { if (!cancelled && request === current) setDetailLoading(false) }
    }
    read(); document.addEventListener("visibilitychange", read)
    return () => { cancelled = true; clearTimeout(timer); request?.abort(); document.removeEventListener("visibilitychange", read) }
  }, [token, selected, reload])

  useEffect(() => {
    setBusy(false); setNotice("")
    return () => { operation.current?.abort(); operation.current = null }
  }, [token, selected])

  async function act(path, method, body, showPreview = false) {
    if (operation.current) return
    const request = new AbortController(); operation.current = request
    setBusy(true); setDetailError("")
    try {
      const result = await apiFetch(path, { method, body, token, signal: request.signal })
      if (request.signal.aborted) return
      if (showPreview) setPreview(result)
      else {
        setPreview(null)
        setReload((value) => value + 1)
        // 서버 결과를 받은 뒤에만 발송 완료를 표시한다.
        setNotice(RESULTS[result.outcome] || (result.status === "needs_review" ? "처리를 보류했습니다. 설정을 확인해 주세요." : "처리 결과를 새로 확인했습니다."))
      }
    } catch (failure) {
      if (!request.signal.aborted) setDetailError(method === "POST" && path.endsWith("/send")
        ? `${failure.message} 발송 상태가 불명확하면 Gmail 보낸편지함을 확인해 주세요.` : failure.message)
    } finally {
      if (operation.current === request) operation.current = null
      if (!request.signal.aborted) setBusy(false)
    }
  }

  const messages = thread?.messages || []
  const processing = thread?.processing || []
  const candidates = thread?.candidates || []
  const gmail = list.connection || state.me?.gmail
  return <section className="mail-page">
    <div className="mail-heading"><div><h1>받은 메일</h1><p>원문과 AI 답장 초안을 확인하고 보낼 내용을 선택하세요.</p></div>
      <a href="/app/settings?section=integrations">{gmail?.connected ? gmail.watch === "active" ? "Gmail 연결됨 · 수집 중" : "Gmail 연결됨 · 수집 확인 필요" : "Gmail 연결하기"}</a>
    </div>
    <form className="mail-toolbar" onSubmit={(event) => { event.preventDefault(); setCursor(null); setQuery(new FormData(event.currentTarget).get("q").trim()) }}>
      <label>메일 검색<input name="q" placeholder="제목 또는 보낸 사람" /></label><button className="btn" type="submit">검색</button>
      <label>상태<select value={filter} onChange={(event) => { setFilter(event.target.value); setCursor(null) }}>
        <option value="">전체</option>{Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label><button className="btn" type="button" onClick={() => setReload((value) => value + 1)}>새로고침</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <div className={`mail-columns ${selected ? "mail-selected" : ""}`}>
      <aside className="mail-list" aria-label="수집한 메일" aria-busy={loading}>
        <p className="mail-caption">연결 이후 수집한 메일입니다. Gmail 과거 전체 목록과는 다를 수 있습니다.</p>
        {loading && !list.items.length ? <p role="status">메일을 불러오는 중…</p> : !list.items.length && <p>표시할 메일이 없습니다.</p>}
        {list.items.map((item) => <button key={item.id} type="button" className={`mail-row ${selected === item.thread_id ? "is-selected" : ""}`}
          aria-current={selected === item.thread_id ? "true" : undefined} onClick={() => setParams({ thread: item.thread_id })}>
          <span className="mail-row-top"><span>{item.from_addr}</span><span className="mail-badge">{item.triage?.phase === "excluded" ? "자동 처리 제외" : STATUS[item.status] || item.status}</span></span>
          <strong>{item.subject || "(제목 없음)"}</strong><span className="mail-snippet">{item.preview}</span><small>{date(item.received_at)}</small>
        </button>)}
        <div className="mail-pagination"><button className="btn" disabled={!cursor} onClick={() => setCursor(null)}>첫 페이지</button>
          <button className="btn" disabled={!list.next_cursor || loading} onClick={() => setCursor(list.next_cursor)}>다음</button></div>
      </aside>
      <article className="mail-detail" aria-label="메일 원문과 답장" aria-busy={detailLoading}>
        {selected && <button type="button" className="btn mail-back" onClick={() => setParams({})}>목록으로</button>}
        {!selected && <p>목록에서 메일을 선택해 주세요.</p>}
        {detailLoading && <p role="status">원문을 불러오는 중…</p>}
        {detailError && <p role="alert">{detailError}</p>}
        {notice && <p role="status">{notice}</p>}
        {thread && <>
          <h2>{messages.at(-1)?.subject || "메일 상세"}</h2>
          <section aria-label="메일 원문"><h3>원문과 대화</h3>
            {messages.map((message) => <details key={message.id} open={message.id === messages.at(-1)?.id}>
              <summary>{message.direction === "out" ? "보낸 메일" : message.from_addr} · {date(message.sent_at)}</summary>
              <p className="mail-recipients">받는 사람: {message.to_addrs.join(", ")}</p><div className="mail-body">{message.body}</div>
            </details>)}
            {!messages.length && <p>원문을 저장하지 않은 처리 제외 메일입니다.</p>}
          </section>
          <section aria-label="메일 처리 상태"><h3>처리 상태</h3>{processing.map((item) => <div key={item.id} className="mail-processing">
            <p>{item.triage?.phase === "excluded" ? "광고·개인·업무 무관으로 판단해 자동 처리를 제외했습니다." : STATUS[item.status] || item.status}</p>
            {item.status === "needs_review" && <p>{NOTICE[item.notice] || "분류 또는 AI 처리 설정을 확인해 주세요. 원문은 보존되어 있습니다."}</p>}
            {(item.status === "needs_review" || item.status === "error" || item.triage?.phase === "excluded") &&
              <button className="btn" type="button" disabled={busy} onClick={() => act(`/mail/messages/${item.id}/process`, "POST")}>업무 메일로 확인 후 처리</button>}
          </div>)}</section>
          <section aria-label="AI 답장 초안"><h3>AI 답장 초안</h3>
            {!candidates.length && <p>{processing.some((item) => item.status === "processing") ? "AI가 처리하고 있습니다…" : "생성된 답장 초안이 없습니다. 알림·제외 메일은 초안을 만들지 않을 수 있습니다."}</p>}
            {candidates.map((candidate) => <section key={candidate.id} className="mail-candidate">
              <h4>{candidate.label} · {candidate.subject}</h4>{candidate.needs_review && <p>내용을 주의 깊게 확인해 주세요.</p>}
              <div className="mail-body">{candidate.body}</div>
              {candidate.quote_id && candidate.document ? <QuotePanel candidate={candidate} token={token} onSaved={() => setReload((value) => value + 1)} /> : candidate.document && <details><summary>관련 문서 · {candidate.document.kind} · {candidate.document.status}</summary>
                <p>발송 시 관련 문서 PDF가 첨부됩니다. 필수 항목이 부족하면 발송되지 않습니다.</p>
                <p>문서번호: {candidate.document.draft.doc_no || candidate.document.draft.quote_no || "미지정"}</p>
                {candidate.trade_doc_id && <a href={`/app/trade/${candidate.document.kind.toLowerCase()}${candidate.document.draft._ci_standalone ? "/standalone" : ""}/${candidate.trade_doc_id}`}>관련 문서 검토하기</a>}
              </details>}
              <button className="btn blue" type="button" disabled={busy || !canSend(candidate)}
                onClick={() => act(`/mail/candidates/${candidate.id}/preview`, "GET", undefined, true)}>{canSend(candidate) ? "발송 내용 확인" : candidate.status === "sent" ? "발송 완료" : "선택할 수 없는 후보"}</button>
            </section>)}
          </section>
        </>}
        {preview && <section ref={confirmation} className="mail-confirm" role="region" aria-label="발송 최종 확인" tabIndex={-1}>
          <h3>이 답장을 보내시겠습니까?</h3><p>받는 사람: {preview.to_addrs.join(", ")}</p><p>제목: {preview.subject}</p>
          <div className="mail-body">{preview.body}</div>{preview.document && <p>첨부: {preview.document.kind} 문서 PDF</p>}
          <p>선택한 답장을 같은 Gmail 대화로 보냅니다.</p>
          <button className="btn blue" type="button" disabled={busy} onClick={() => act(`/mail/candidates/${preview.id}/send`, "POST", { revision: preview.document?.revision ?? null })}>{busy ? "보내는 중…" : "확인하고 보내기"}</button>
          <button className="btn" type="button" disabled={busy} onClick={() => setPreview(null)}>취소</button>
        </section>}
      </article>
    </div>
  </section>
}
