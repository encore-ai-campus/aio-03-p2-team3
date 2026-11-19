import FollowupPanel from "./FollowupPanel"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { apiFetch } from "../api"
import { useAuth } from "../useAuth"
import "./mailbox.css"
import QuotePanel from "./QuotePanel"
import ReplyCandidateEditor from "./ReplyCandidateEditor"

const STATUS = { processing: "처리 중", awaiting_approval: "답장 대기", sent: "보냄",
  error: "처리 오류", ignored: "초안 없음", needs_review: "확인 필요" }
// 상태 탭: 행동이 필요한 순서로. 나머지 상태는 '전체'에서 상태 필로 확인한다.
const TABS = [
  { key: "awaiting_approval", label: "답장 대기" },
  { key: "needs_review", label: "확인 필요" },
  { key: "processing", label: "처리 중" },
  { key: "", label: "전체" },
]
const PILL = { awaiting_approval: "awaiting", needs_review: "review", sent: "sent",
  processing: "processing", error: "err", ignored: "off", excluded: "off" }
const DOC_LABEL = { quote: "국내 견적", pi: "PI", po: "PO", ci: "CI", pl: "PL" }
const RESULTS = { sent: "메일을 보냈습니다.", already_sent: "이미 발송했거나 처리한 후보입니다.",
  failed_unknown: "발송 여부를 확인하지 못했습니다. Gmail 보낸편지함을 확인한 뒤 다시 승인해 주세요.",
  failed_auth: "Gmail 권한을 확인하고 다시 연결해 주세요.", failed: "발송에 실패했습니다. 연결과 문서를 확인해 주세요.",
  needs_input: "관련 문서의 필수 항목을 먼저 확인해 주세요.", needs_seal: "회사 직인을 먼저 등록해 주세요.",
  needs_price: "관련 국내 견적서에서 빠진 단가를 먼저 입력해 주세요.",
  needs_pi_source: "CI의 PI 원문 근거를 먼저 확인해 주세요.", document_changed: "문서가 변경됐습니다. 최신 내용을 다시 확인해 주세요." }
const NOTICE = { local_worker_key_forbidden: "개인 PC 실행 방식은 자동 분류를 지원하지 않습니다. 업무 메일로 확인 후 처리할 수 있습니다.",
  processing_interrupted: "AI 처리 중 서버가 재시작됐습니다. 저장된 내용을 확인한 뒤 다시 처리해 주세요.",
  connection_changed: "처리 중 Gmail 연결이 바뀌었습니다. 연결 상태를 확인해 주세요." }
const date = (value) => value ? new Date(value).toLocaleString("ko-KR") : ""
const shortDate = (value) => {
  if (!value) return ""
  const at = new Date(value), now = new Date()
  return at.toDateString() === now.toDateString()
    ? at.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : `${String(at.getMonth() + 1).padStart(2, "0")}/${String(at.getDate()).padStart(2, "0")}`
}
const clock = (value) => value ? value.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : ""
const canSend = (candidate) => ["pending", "send_failed"].includes(candidate.status)
const needsPrice = (candidate) => candidate.document?.status === "needs_price"
const enter = (index) => ({ "--i": String(index) })

// 인라인 아이콘(시안 docs/plans/mailbox-ui와 같은 도형).
const svg = (children) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
    strokeLinejoin="round" aria-hidden="true">{children}</svg>
)
const IC = {
  search: svg(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>),
  x: svg(<path d="M6 6l12 12M18 6L6 18" />),
  refresh: svg(<><path d="M21 12a9 9 0 1 1-2.6-6.3" /><path d="M21 3v6h-6" /></>),
  chev: svg(<path d="M6 9l6 6 6-6" />),
  back: svg(<path d="M15 6l-6 6 6 6" />),
  arrow: svg(<><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></>),
  mail: svg(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>),
  send: svg(<><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>),
  file: svg(<><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /></>),
  clock: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></>),
  warn: svg(<><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>),
  check: svg(<path d="M20 6L9 17l-5-5" />),
}

function statusPill(item) {
  if (item.triage?.phase === "excluded") return <span className="pill off">자동 처리 제외</span>
  return <span className={`pill ${PILL[item.status] || "off"}`}>
    {item.status === "processing" && <i className="pd" aria-hidden="true" />}
    {STATUS[item.status] || item.status}
  </span>
}

// 첨부 요약: 견적은 번호와 PDF만(금액은 초안 본문·견적서 상세와 겹침), 일반 답장은 첨부 없음을 알린다.
function attachRow(candidate) {
  const doc = candidate.document
  if (!doc) return <div className="attach"><span className="file">{IC.mail} 문서 첨부 없음</span>
    <span className="sum">답장 본문만 전송됩니다</span></div>
  if (candidate.quote_id) return <div className={`attach ${doc.status === "needs_price" ? "warn" : ""}`}>
    <span className="file">{IC.file} 국내 견적 {doc.draft?.quote_no}</span>
    <span className="sum">{doc.status === "needs_price" ? "빠진 단가 미입력" : "PDF 첨부"}</span>
  </div>
  return <div className="attach"><span className="file">{IC.file} 무역 문서 {doc.draft?.doc_no || DOC_LABEL[doc.kind] || doc.kind}</span>
    <span className="sum">PDF 첨부</span></div>
}

function tradeLink(candidate) {
  if (!candidate.trade_doc_id || !candidate.document) return null
  const kind = candidate.document.kind.toLowerCase()
  const standalone = candidate.document.draft?._ci_standalone ? "/standalone" : ""
  return <a className="btn" href={`/app/trade/${kind}${standalone}/${candidate.trade_doc_id}`}>관련 문서 검토하기</a>
}

export default function MailboxPage() {
  const [params] = useSearchParams()
  const { state } = useAuth()
  return params.get("followups") === "1" ? <FollowupPanel key={state.accessToken} token={state.accessToken} /> : <Mailbox />
}

function Mailbox() {
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
  const [editingCandidate, setEditingCandidate] = useState(null)
  const [stampedAt, setStampedAt] = useState(null)
  const [reload, setReload] = useState(0)
  const operation = useRef(null)
  const confirmation = useRef(null)
  const tabsRef = useRef(null)
  const inkRef = useRef(null)

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
        if (!cancelled && request === current) { setList(data); setStampedAt(new Date()); setError("") }
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
    setThread(null); setDetailError(""); setPreview(null); setEditingCandidate(null)
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
    setBusy(false); setNotice(""); setEditingCandidate(null)
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

  // 발송 확인 모달: 열리면 포커스를 옮기고 Esc로 닫는다.
  useEffect(() => {
    if (!preview) return
    confirmation.current?.focus()
    const onKey = (event) => { if (event.key === "Escape") setPreview(null) }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [preview])

  // 결과 토스트는 잠시 뒤 저절로 사라진다.
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(""), 4200)
    return () => clearTimeout(timer)
  }, [notice])

  // 탭 밑줄이 활성 탭 위치로 슬라이드한다.
  useLayoutEffect(() => {
    const active = tabsRef.current?.querySelector('[aria-selected="true"]')
    if (!active || !tabsRef.current || !inkRef.current) return
    inkRef.current.style.width = `${active.offsetWidth}px`
    inkRef.current.style.transform = `translateX(${active.offsetLeft - tabsRef.current.offsetLeft}px)`
  }, [filter, list])

  const counts = list.status_counts ?? {}
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0)
  const messages = thread?.messages || []
  const processing = thread?.processing || []
  const candidates = thread?.candidates || []
  const lastMessage = messages.at(-1)
  const lastProcessing = processing.at(-1)

  return <section className="mail-page">
    <div className="page-head enter" style={enter(0)}>
      <h1 className="page-title">받은 메일</h1>
      <p className="page-sub">원문과 AI 답장 초안을 확인하고, 보낼 답장을 골라 승인하세요.</p>
      <Link className="doc-link" to="/inbox?followups=1">메일 후속 알림</Link>
    </div>
    <div className="mailbar enter" style={enter(1)}>
      <div className="tabs" role="tablist" aria-label="상태별 메일" ref={tabsRef}>
        {TABS.map((tab) => <button key={tab.label} type="button" role="tab" className="tab"
          aria-selected={filter === tab.key} onClick={() => { setFilter(tab.key); setCursor(null) }}>
          {tab.label} <span className="count num">{tab.key ? counts[tab.key] ?? 0 : total}</span>
        </button>)}
        <span className="tab-ink" aria-hidden="true" ref={inkRef} />
      </div>
      <form className="search" onSubmit={(event) => {
        event.preventDefault(); setCursor(null); setQuery(new FormData(event.currentTarget).get("q").trim())
      }}>
        {IC.search}
        <input key={`q-${query}`} name="q" type="search" placeholder="제목 또는 보낸 사람"
          defaultValue={query} aria-label="메일 검색" autoComplete="off" />
        {query && <button type="button" className="clear" aria-label="검색어 지우기"
          onClick={() => { setQuery(""); setCursor(null) }}>{IC.x}</button>}
      </form>
      <span className="fresh">
        <button type="button" className="icon-btn" aria-label="새로고침" onClick={() => setReload((value) => value + 1)}>{IC.refresh}</button>
        {stampedAt && <span className="num">{clock(stampedAt)} 갱신</span>}
      </span>
    </div>
    {error && <p role="alert" className="mail-alert">{error}</p>}
    <div className={`mail-columns enter ${selected ? "mail-selected" : ""}`} style={enter(2)}>
      <aside className="pane pane-list" aria-label="수집한 메일" aria-busy={loading}>
        <div className="pane-head"><p>연결 이후 수집한 메일입니다. Gmail 과거 전체 목록과는 다를 수 있습니다.</p></div>
        <div className="pane-scroll"><div className="rows">
          {loading && !list.items.length ? <p role="status" className="plain padded">메일을 불러오는 중…</p>
            : !list.items.length ? <p className="plain padded">표시할 메일이 없습니다.</p>
              : list.items.map((item, index) => <button key={item.id} type="button"
                className={`mail-row enter ${selected === item.thread_id ? "is-selected" : ""}`} style={enter(index % 12)}
                aria-current={selected === item.thread_id ? "true" : undefined}
                onClick={() => setParams({ thread: item.thread_id })}>
                <span className="row-top"><span className="who">{item.from_addr}</span>
                  <span className="when num">{shortDate(item.received_at)}</span></span>
                <span className="row-bot"><span className="what">{item.subject || "(제목 없음)"}</span>
                  {statusPill(item)}</span>
              </button>)}
        </div></div>
        <div className="pane-foot">
          <span className="num">{list.items.length}건{list.next_cursor ? "+" : ""}</span>
          <span className="pager">
            <button className="btn sm" type="button" disabled={!cursor} onClick={() => setCursor(null)}>첫 페이지</button>
            <button className="btn sm" type="button" disabled={!list.next_cursor || loading}
              onClick={() => setCursor(list.next_cursor)}>다음</button>
          </span>
        </div>
      </aside>
      <article className="pane pane-detail" aria-label="메일 원문과 답장" aria-busy={detailLoading}>
        {!selected && <p className="plain padded">목록에서 메일을 선택해 주세요.</p>}
        {detailLoading && <p role="status" className="plain padded">원문을 불러오는 중…</p>}
        {detailError && <p role="alert" className="plain padded">{detailError}</p>}
        {thread && <div className="pane-scroll" key={thread.thread_id}>
          <div className="detail-head enter">
            <button type="button" className="back" onClick={() => setParams({})}>{IC.back}목록으로</button>
            <h2>{lastMessage?.subject || "메일 상세"}</h2>
            <div className="detail-meta">
              {lastMessage && <>
                <span className="addr">{lastMessage.from_addr}</span>
                <span className="flow">{IC.arrow}<span className="addr">{lastMessage.to_addrs.join(", ")}</span></span>
                <span className="num">{date(lastMessage.sent_at)}</span>
              </>}
              {lastProcessing && statusPill(lastProcessing)}
            </div>
          </div>
          <div className="detail-body">
            <section className="sec enter" aria-label="메일 원문"><h3>{IC.mail} 원문과 대화</h3>
              {messages.map((message) => <details key={message.id}
                className={`msg ${message.direction === "out" ? "out" : ""}`}
                open={message.id === lastMessage?.id}>
                <summary className="msg-head">
                  <span className="dir">{message.direction === "out" ? IC.send : IC.mail}</span>
                  <span className="mwho">{message.direction === "out" ? "보낸 메일" : message.from_addr}</span>
                  <span className="mwhen num">{date(message.sent_at)}</span>
                  {IC.chev}
                </summary>
                <div className="msg-body">
                  <p className="mto">받는 사람: {message.to_addrs.join(", ")}</p>
                  <div className="mail-body">{message.body}</div>
                </div>
              </details>)}
              {!messages.length && <p className="plain">원문을 저장하지 않은 처리 제외 메일입니다.</p>}
            </section>
            {processing.length > 0 && <section className="sec enter" aria-label="메일 처리 상태"><h3>{IC.clock} 처리 상태</h3>
              {processing.map((item) => item.status === "processing"
                ? <div key={item.id} className="proc">
                  <p className="p-top"><i className="pd" aria-hidden="true" />AI가 메일을 분석하고 답장 초안을 만들고 있습니다<span className="ell" aria-hidden="true"><i /><i /><i /></span></p>
                  <div className="track" aria-hidden="true"><i /></div>
                  <p className="p-sub">메일 분석 · 필수 항목 확인 · 초안 작성 · 이 화면을 나가도 계속됩니다</p>
                </div>
                : <div key={item.id} className={`notice ${item.status === "needs_review" ? "" : "plain"}`}>{IC.warn}
                  <span>{item.triage?.phase === "excluded"
                    ? "광고·개인·업무 무관으로 판단해 자동 처리를 제외했습니다. 업무 메일이면 아래 버튼으로 처리할 수 있습니다."
                    : item.status === "needs_review"
                      ? NOTICE[item.notice] || "분류 또는 AI 처리 설정을 확인해 주세요. 원문은 보존되어 있습니다."
                      : STATUS[item.status] || item.status}</span>
                  {(item.status === "needs_review" || item.status === "error" || item.triage?.phase === "excluded") &&
                    <button className="btn sm" type="button" disabled={busy}
                      onClick={() => act(`/mail/messages/${item.id}/process`, "POST")}>업무 메일로 확인 후 처리</button>}
                </div>)}
            </section>}
            {processing.some(item => item.inbound_context) && <section className="sec enter" aria-label="초안에 참고한 자료">
              <h3>초안에 참고한 자료</h3>
              {processing.filter(item => item.inbound_context).map(item => {
                const { calendar, knowledge } = item.inbound_context
                const status = { available: "요청 시간에 일정 충돌이 없습니다.", busy: "요청 시간에 기존 일정이 겹칩니다.",
                  unspecified: "요청 시간을 더 확인해야 합니다.", duration_required: "미팅에 필요한 시간을 확인해야 합니다.",
                  outside_window: "요청 시간이 조회 기간을 벗어났습니다.", unavailable: "캘린더에서 가능 여부를 확인하지 못했습니다." }
                return <div key={item.id}>
                  {calendar && <p>{status[calendar.status]}</p>}
                  {knowledge?.clauses.length > 0 && <>
                    <p>{knowledge.scope === "counterparty" ? "거래처에 연결된 계약서" : "내 문서함의 검토 자료"}</p>
                    <ul>{knowledge.clauses.map(clause => <li key={clause.clause_id}>
                      <Link to={`/documents?document=${encodeURIComponent(clause.document_id)}`}>{clause.filename}</Link>
                      {clause.sources.map((source, index) => <span key={index}> · {source.source || `페이지 ${source.page}`}</span>)}
                    </li>)}</ul>
                  </>}
                  {knowledge?.status === "no_evidence" && <p>관련 조항을 찾지 못했습니다.</p>}
                  {knowledge?.status === "unavailable" && <p>문서 검색을 완료하지 못했습니다.</p>}
                </div>
              })}
            </section>}
            <section className="sec enter" aria-label="AI 답장 초안"><h3>{IC.send} AI 답장 초안</h3>
              {!candidates.length && <p className="plain">{processing.some((item) => item.status === "processing")
                ? "AI가 처리하고 있습니다…" : "생성된 답장 초안이 없습니다. 알림·제외 메일은 초안을 만들지 않을 수 있습니다."}</p>}
              {candidates.map((candidate) => <section key={candidate.id}
                className={`mail-candidate ${candidate.status === "sent" ? "is-sent" : ""}`}>
                <div className="cand-head">
                  <span className={`tag ${candidate.status === "sent" ? "dim" : ""}`}>{candidate.label}</span>
                  <span className="csub">{candidate.subject}</span>
                </div>
                {candidate.needs_review && <p className="cand-note">내용을 주의 깊게 확인해 주세요.</p>}
                <ReplyCandidateEditor candidate={candidate} token={token} busy={busy}
                   onEditingChange={setEditingCandidate} onSaved={() => setReload((value) => value + 1)}
                   onError={setDetailError} />
                {attachRow(candidate)}
                {candidate.quote_id && candidate.document &&
                  <QuotePanel candidate={candidate} token={token} onSaved={() => setReload((value) => value + 1)} />}
                <div className="cand-actions">
                  {candidate.status === "sent"
                    ? <span className="sent-line">{IC.check}발송 완료</span>
                    : canSend(candidate)
                      ? <button className="btn blue" type="button"
                        disabled={busy || editingCandidate !== null || needsPrice(candidate)}
                        onClick={() => act(`/mail/candidates/${candidate.id}/preview`, "GET", undefined, true)}>
                        발송 내용 확인 {IC.arrow}
                      </button>
                      : <button className="btn" type="button" disabled>선택할 수 없는 후보</button>}
                  {canSend(candidate) && needsPrice(candidate) && <span className="why">빠진 단가를 먼저 입력해 주세요</span>}
                  {tradeLink(candidate)}
                </div>
              </section>)}
            </section>
          </div>
        </div>}
      </article>
    </div>
    {preview && <div className="overlay" onClick={(event) => { if (event.target === event.currentTarget) setPreview(null) }}>
      <section ref={confirmation} className="modal" role="region" aria-label="발송 최종 확인" tabIndex={-1}>
        <div className="modal-head">
          <h2>이 답장을 보내시겠습니까?</h2>
          <button className="close" type="button" aria-label="닫기" onClick={() => setPreview(null)}>{IC.x}</button>
        </div>
        <div className="modal-body">
          <p className="mk">받는 사람: {preview.to_addrs.join(", ")}</p>
          <p className="mk">제목: {preview.subject}</p>
          <div className="cand-body boxed">{preview.body}</div>
          {preview.document
            ? <p className="attach-note">{IC.file} 첨부: {DOC_LABEL[preview.document.kind] || preview.document.kind} 문서 PDF</p>
            : <p className="attach-note">{IC.mail} 첨부 없음 · 답장 본문만 전송됩니다</p>}
        </div>
        <div className="modal-foot">
          <span className="note">선택한 답장을 같은 Gmail 대화로 보냅니다.</span>
          <button className="btn" type="button" disabled={busy} onClick={() => setPreview(null)}>취소</button>
          <button className="btn blue" type="button" disabled={busy}
            onClick={() => act(`/mail/candidates/${preview.id}/send`, "POST", { revision: preview.document?.revision ?? null,
               expected_subject: preview.subject, expected_body: preview.body })}>
            {busy ? "보내는 중…" : "확인하고 보내기"}
          </button>
        </div>
      </section>
    </div>}
    {notice && <div className="toast" role="status">{IC.check}<span>{notice}</span></div>}
  </section>
}
