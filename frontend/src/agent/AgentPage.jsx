import { Fragment, useEffect, useId, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, appHref } from "../api"
import { useAuth } from "../useAuth"
import { dateKey, formatEventWhen } from "../calendar/useCalendarEvents"
import ReviewCard from "./ReviewCard"
import DocCard, { FileButtons } from "./DocCard"
import AssistantMarkdown from "./AssistantMarkdown"
import { AttachmentResult, FollowupResult, SentMailResult } from "./MailWorkResult"
import MailSearchResult from "./MailSearchResult"
import ComposeDraftCard from "./ComposeDraftCard"
import TradeDraftResult from "./TradeDraftResult"
import { CalendarInterval } from "./CalendarChangeCard"
import { CounterpartyResult, TradePriceResult } from "./TradeDirectoryResult"
import "./agent.css"

const STATUS = { running: "처리 중", needs_input: "답변 대기", needs_approval: "승인 대기", completed: "응답 완료",
  error: "확인 필요", interrupted: "실행 중단", review: "실행 결과 확인 필요" }
const ERRORS = { OPENAI_KEY_REQUIRED: "설정에서 본인의 OpenAI 키를 등록해 주세요.",
  LOCAL_WORKER_KEY_FORBIDDEN: "대화형 에이전트는 현재 서버 저장 키 또는 로컬 실행을 지원합니다.",
  agent_step_limit: "이번 요청의 처리 횟수에 도달했습니다. 결과를 확인하고 요청을 나눠 주세요.",
  agent_model_failed: "AI 요청에 실패했습니다. 저장된 결과를 확인하고 다시 요청해 주세요.",
  agent_execution_failed: "처리가 중단됐습니다. 저장된 상태를 다시 확인해 주세요." }
Object.assign(ERRORS, { agent_model_network: "AI 연결이 끊겼습니다. 저장된 결과를 확인하고 다시 요청해 주세요.",
  agent_model_rate_limit: "AI 사용 한도에 도달했습니다. 설정한 키의 사용량을 확인해 주세요.",
  agent_model_invalid_input: "AI 모델이 도구 요청을 거절했습니다. 모델 설정과 도구 지원 여부를 확인해 주세요.",
  agent_model_internal: "AI 요청을 처리하지 못했습니다. 저장된 결과를 확인해 주세요." })
const OPERATIONS = { search: "메일 검색", query: "원문 조회", draft: "초안 작성", compose: "새 메일 초안", edit_reply: "답장 초안 수정", get: "문서 조회", schema: "입력 조건 확인",
  issue: "파일 발급", approve_packing: "포장 합계 승인", send: "답장 발송", search_issued: "발급 문서 검색", search_drafts: "무역서류 초안 조회",
  search_knowledge: "문서함 검색", search_trade_prices: "등록 단가 조회",
  search_counterparties: "거래처 정보 조회", list_events: "캘린더 일정 조회",
  attachments: "메일 첨부 조회", search_sent: "발송 메일 검색", register_followup: "후속 알림 등록",
  list_followups: "후속 알림 조회", cancel_followup: "후속 알림 취소", move_event: "일정 변경", cancel_event: "일정 취소" }
const OUTCOMES = { completed: "완료", failed: "실패", cancelled: "취소", needs_review: "확인 필요", unknown: "결과 확인 필요", blocked: "선행 작업 확인 필요" }
const PROGRESS_STATUS = { running: "진행 중", completed: "완료", failed: "실패",
  review: "확인 필요", interrupted: "중단" }

function Icon({ name }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>,
    query: <><path d="M3 6h18M3 6v12a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V6M3 6l9 7 9-7" /></>,
    draft: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>,
    get: <><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /></>,
    schema: <><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" /></>,
    issue: <><path d="M12 3v12" /><path d="M7 10l5 5 5-5" /><path d="M4 21h16" /></>,
    approve_packing: <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M8 12l3 3 5-6" /></>,
    send: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>,
  }
  return <svg className="op-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.get}</svg>
}

const KNOWLEDGE_STATUS = {
  choose_document: "이름이 일치하는 문서가 여러 개입니다. 파일을 골라 주세요.",
  not_found: "문서함에서 조건에 맞는 파일을 찾지 못했습니다.",
  not_indexed: "파일은 열 수 있습니다. 내용 검색은 문서 처리가 완료된 뒤 가능합니다.",
  no_evidence: "답변에 필요한 문서함 근거를 찾지 못했습니다.",
}

const FILE_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h4" /></svg>
const QUOTE_ICON = <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10 7H6a3 3 0 0 0-3 3v4a3 3 0 0 0 3 3h2a1 1 0 0 0 1-1v-3H6v-3h4zm11 0h-4a3 3 0 0 0-3 3v4a3 3 0 0 0 3 3h2a1 1 0 0 0 1-1v-3h-3v-3h4z" /></svg>

function KnowledgeResult({ data }) {
  return <>
    {KNOWLEDGE_STATUS[data.knowledge_status] && <p>{KNOWLEDGE_STATUS[data.knowledge_status]}</p>}
    {data.knowledge_documents?.length > 0 && <div className="attach-row">{data.knowledge_documents.map(document =>
      <a className="attach-chip" href={appHref(document.url)} target="_blank" rel="noreferrer" key={document.document_id}>
        {FILE_ICON}{document.filename}</a>)}</div>}
    {data.knowledge_clauses?.map(clause => <article className="cite-card" key={clause.clause_id}>
      <div className="cite-src">
        <a className="file-chip" href={appHref(clause.url)} target="_blank" rel="noreferrer">{FILE_ICON}{clause.filename}</a>
        {clause.sources.map((source, index) => <span className="page-chip" key={index}>{source.source || `${source.page}p`}</span>)}
      </div>
      <p className="cite-text">{QUOTE_ICON}<span>{clause.text}</span></p>
    </article>)}
  </>
}

const FALLBACK_LABELS = { kind: "문서 종류", document_id: "문서 ID", status: "상태", revision: "버전", counterparty: "거래처",
  updated_at: "마지막 수정", issued_on: "발급일", total: "합계", currency: "통화", run_id: "실행 ID",
  end_reason: "종료 사유", needs_review: "확인 필요", candidate_id: "후보 ID" }

function FallbackKV({ data }) {
  const entries = Object.entries(data || {})
  const simple = entries.length > 0 && entries.every(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value))
  if (!simple) return <pre>{JSON.stringify(data, null, 2)}</pre>
  return <dl className="kv">{entries.map(([key, value]) => <div className="kv-row" key={key}>
    <dt>{FALLBACK_LABELS[key] || key}</dt>
    <dd>{value === null ? "—" : typeof value === "boolean" ? (value ? "예" : "아니오") : String(value)}</dd>
  </div>)}</dl>
}

function StepDetail({ item, token, onError }) {
  const issued = item.data?.issued_documents
  const events = item.data?.events
  const calendarChange = ["move_event", "cancel_event"].includes(item.operation)
  const calendarEvent = item.data?.calendar_event
  const eventErrors = { calendar_event_changed: "일정이 바뀌었습니다. 최신 일정을 다시 확인해 주세요.",
    calendar_event_lookup_required: "먼저 캘린더에서 변경할 일정을 찾아 주세요.",
    calendar_select_occurrence: "반복 일정에서 변경할 회차를 선택해 주세요.",
    calendar_move_conflict: "이 시각에는 다른 일정이 있습니다.",
    calendar_unconfirmed: "변경 결과를 확인해야 합니다.",
    calendar_rejected: "Google 캘린더가 변경 요청을 거절했습니다.",
    gmail_not_connected: "설정에서 Gmail을 연결해 주세요.",
    mail_attachment_unavailable: "Gmail 원본 첨부를 읽을 수 없습니다.",
    mail_attachment_source_missing: "원본 메일을 찾을 수 없습니다.",
    mail_attachment_lookup_required: "원본 메시지를 먼저 확인해 주세요.",
    followup_requires_sent_mail: "수집된 발송 기록이 있는 메일을 골라 주세요.",
    followup_invalid_due: "현재부터 1년 이내의 미래 시각을 지정해 주세요.",
    followup_lookup_required: "후속 알림 목록에서 취소할 알림을 확인해 주세요.",
    followup_mail_lookup_required: "기준이 될 발송 메일을 먼저 확인해 주세요.",
    past_slot: "미래 시각을 선택해 주세요.",
    calendar_invalid_move_time: "종일 일정은 날짜를, 시간 일정은 새 시작 시각을 지정해 주세요." }
  const prices = item.data?.prices
  const counterparties = item.data?.counterparties
  return <>
    {item.code && item.code !== "calendar_write_required" && <p>{eventErrors[item.code] || item.code}</p>}
    {item.code === "calendar_write_required" && <p>일정을 변경하려면 <Link to="/settings">설정에서 Google 캘린더 쓰기 권한</Link>을 추가해 주세요.</p>}
    {calendarEvent && <div className="calendar-action-card">
      <h3>{calendarEvent.summary || "(제목 없음)"}</h3>
      <p>{item.data.calendar_outcome === "cancelled" ? "일정 취소 완료" : item.data.outcome === "already_at_time" ? "이미 요청한 시각에 등록됨" : "일정 이동 완료"}</p>
      <CalendarInterval value={calendarEvent} />
    </div>}
    {item.data?.calendar_conflicts?.map(event => <p key={event.id}>{event.summary || "(제목 없음)"} · <CalendarInterval value={event} /></p>)}
    {item.data?.compose_draft && <ComposeDraftCard draftId={item.data.compose_draft.id} token={token} />}
    {item.data?.mail_attachments && <AttachmentResult files={item.data.mail_attachments} token={token} onError={onError} />}
    {item.data?.followups && <FollowupResult data={item.data} />}
    {item.data?.sent_threads && <SentMailResult data={item.data} />}
    {Array.isArray(item.data?.threads) && <MailSearchResult data={item.data} />}
    {item.data?.messages?.map(message => <article key={message.gmail_message_id}><b>{message.subject}</b><p>{message.from_addr}</p>
      <p className="agent-text">{message.body_text}</p></article>)}
    {item.data?.candidates?.some(Boolean) && <div className="cand-list">{item.data.candidates.map(candidate => candidate &&
      <article className="cand" key={candidate.id}>
        <div className="cand-top"><span className="cand-no">#{candidate.id}</span><span className="cand-title">{candidate.label}</span></div>
        {candidate.subject && <p className="cand-subject">{candidate.subject}</p>}
        <p className="cand-preview">{candidate.body}</p>
      </article>)}</div>}
    {item.data?.document_id && item.kind && <p><Link to={`/trade/${item.kind.toLowerCase()}/${item.data.document_id}`}>{item.kind} 문서 #{item.data.document_id} 열기</Link></p>}
    {item.data?.edited_reply && <div className="compose-draft-result">
      <b>{item.data.edited_reply.subject}</b><p className="agent-text">{item.data.edited_reply.body}</p>
      <p role="status">답장 초안에 저장했습니다.</p>
    </div>}
    {item.data?.sent_message_id && <p role="status">메일을 보냈습니다.</p>}
    {item.data?.files?.length > 0 && <div className="doc-files"><FileButtons files={item.data.files} token={token} onError={onError} /></div>}
    {item.data?.draft_documents && <TradeDraftResult data={item.data} />}
    {issued?.length === 0 && <p>조건에 맞는 발급 문서가 없습니다.</p>}
    {issued?.map(document => <DocCard key={document.proposal_id} chip={document.kind} chipClass={document.kind?.toLowerCase()}
      number={document.document_number}
      meta={[document.counterparty, document.issued_on && `${document.issued_on} 발급`, document.revision && `버전 ${document.revision}`].filter(Boolean).join(" · ")}
      link={`/trade/${document.kind.toLowerCase()}/${document.document_id}`}
      files={document.files} token={token} onError={onError} />)}
    {prices ? <TradePriceResult data={item.data} /> : counterparties && <CounterpartyResult data={item.data} />}
    {item.data?.knowledge_status && <KnowledgeResult data={item.data} />}
    {events?.length === 0 && <p>이 기간에 등록된 일정이 없습니다.</p>}
    {item.data?.total > events?.length && <p>전체 {item.data.total}건 중 {events.length}건을 표시합니다.</p>}
    {events?.length > 0 && <ul>{events.map(event => <li key={event.id}>
      <b>{event.summary || "(제목 없음)"}</b> · {event.all_day ? event.start : dateKey(new Date(event.start))} {formatEventWhen(event)}
    </li>)}</ul>}
    {item.operation === "schema" && <p>문서 작성에 필요한 입력 조건을 확인했습니다.</p>}
    {!item.data?.threads && !item.data?.messages && !item.data?.candidates && !item.data?.files && !issued &&
      !item.data?.knowledge_status && !item.data?.mail_attachments && !item.data?.followups && !item.data?.sent_threads && !item.data?.draft_documents && !item.data?.compose_draft && !item.data?.edited_reply && !events && !calendarChange && !prices && !counterparties && item.operation !== "schema" &&
      <FallbackKV data={item.data} />}
  </>
}

function Step({ item, token, onError }) {
  const [open, setOpen] = useState(false)
  const label = OPERATIONS[item.operation] || "업무 처리"
  const outcome = OUTCOMES[item.status] || "결과 확인 필요"
  return <li className={`step${open ? " open" : ""}`}>
    <button type="button" className="step-head" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Icon name={item.operation} />
      <span className="step-name">{label}</span>
      <span className="step-sep" aria-hidden="true"> · </span>
      <span className={`step-outcome ${item.status}`}>{outcome}</span>
      <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
    </button>
    <div className="step-body"><div><div className="step-detail">{(open || !item.data?.compose_draft) && <StepDetail item={item} token={token} onError={onError} />}</div></div></div>
  </li>
}

function ElapsedTime({ startedAt, finishedAt, running }) {
  const start = Date.parse(startedAt)
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!running) return
    const tick = () => setNow(Date.now())
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [running, start])
  const end = running ? now : Date.parse(finishedAt)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  const minutes = Math.floor(seconds / 60)
  return <time dateTime={`PT${seconds}S`}>{minutes ? `${minutes}분 ${seconds % 60}초` : `${seconds}초`}</time>
}

function WorkTimeline({ results, running, progress, status, token, onError }) {
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  if (!running && !progress && !results.length) return null
  const steps = progress?.steps || []
  const attention = results.some(item => item.status !== "completed")
  const names = results.map(item => OPERATIONS[item.operation] || "업무 처리").slice(0, 3).join(" · ") + (results.length > 3 ? ` 외 ${results.length - 3}` : "")
  return <div className={`work${open ? " open" : ""}${running ? " running" : ""}`}>
    <button type="button" className="work-row" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(value => !value)}>
      <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      {running
        ? <span className="work-state" key="run"><svg className="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
          {progress ? <><ElapsedTime startedAt={progress.started_at} running /> 동안 작업 중</> : "업무 처리 중"}
        </span>
        : progress
          ? <span className={`work-state${status === "completed" ? "" : " warn"}`}>{STATUS[status]} · <ElapsedTime startedAt={progress.started_at} finishedAt={progress.finished_at} /></span>
          : attention
          ? <span className="work-state warn" key="warn"><svg className="ok-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 16.5v.5" /><circle cx="12" cy="12" r="9" /></svg>확인 필요 · {results.length}단계</span>
          : <span className="work-state" key="ok"><svg className="ok-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>업무 완료 · {results.length}단계</span>}
      {!progress && <span className="work-meta">{names}</span>}
    </button>
    <div className="work-body" id={bodyId} inert={!open}><div>
      {steps.length > 0 && <ol aria-label="이번 요청의 작업 단계">
        {steps.map((step, index) => <li className={`progress-step ${step.status}`} key={index}>
          <span>{step.label}</span><span>{PROGRESS_STATUS[step.status]}</span>
        </li>)}
      </ol>}
      {running && !steps.length && <p className="progress-placeholder">작업 시작을 기다리고 있습니다.</p>}
      {!running && results.length > 0 && <ol aria-label="작업 결과">
        {results.map((item, index) => <Step key={item.task_id || index} item={item} token={token} onError={onError} />)}
      </ol>}
    </div></div>
  </div>
}

export default function AgentPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const { conversationId = "" } = useParams()
  const navigate = useNavigate()
  const [list, setList] = useState([])
  const [loadedView, setView] = useState(null)
  const view = loadedView?.token === token && loadedView?.data.id === conversationId ? loadedView.data : null
  const [text, setText] = useState("")
  const [error, setError] = useState("")
  const [readError, setReadError] = useState("")
  const [submittedAt, setSubmittedAt] = useState(null)
  const busy = submittedAt !== null
  const [reload, setReload] = useState(0)
  const [historyOpen, setHistoryOpen] = useState(false)
  const operation = useRef(null)
  const stick = useRef(true)
  const endRef = useRef(null)

  useEffect(() => {
    const request = new AbortController()
    apiFetch("/agent/conversations", { token, signal: request.signal }).then(setList).catch(failure => {
      if (failure.name !== "AbortError") setError(failure.message)
    })
    return () => request.abort()
  }, [token, reload])

  useEffect(() => {
    let cancelled = false, timer, request
    setError(""); setReadError(""); setText(""); setSubmittedAt(null)
    operation.current?.abort()
    async function read() {
      clearTimeout(timer)
      if (!conversationId || document.hidden) return
      request?.abort(); request = new AbortController()
      try {
        const data = await apiFetch(`/agent/conversations/${conversationId}`, { token, signal: request.signal })
        if (cancelled) return
        setReadError("")
        setView({ token, data })
        setList(items => [{ id: data.id, title: data.title, status: data.status }, ...items.filter(item => item.id !== data.id)])
        if (data.status === "running") timer = setTimeout(read, 2000)
      } catch (failure) {
        if (cancelled || failure.name === "AbortError") return
        setReadError(failure.message)
        if (failure.status === 0 || failure.status >= 500) timer = setTimeout(read, 2000)
      }
    }
    read(); document.addEventListener("visibilitychange", read)
    return () => { cancelled = true; clearTimeout(timer); request?.abort(); operation.current?.abort(); document.removeEventListener("visibilitychange", read) }
  }, [conversationId, token, reload])

  useEffect(() => () => operation.current?.abort(), [])

  useEffect(() => {
    const onScroll = () => { stick.current = window.innerHeight + window.scrollY >= document.body.scrollHeight - 180 }
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  useEffect(() => {
    if (stick.current && endRef.current) {
      try { endRef.current.scrollIntoView({ behavior: "smooth", block: "end" }) } catch { endRef.current.scrollIntoView() }
    }
  }, [view?.messages?.length, view?.results?.length, view?.waiting, view?.status])

  useEffect(() => {
    const onKey = event => { if (event.key === "Escape") setHistoryOpen(false) }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  async function send(path, body) {
    if (busy) return
    const request = new AbortController()
    operation.current?.abort(); operation.current = request
    setSubmittedAt(new Date().toISOString()); setError("")
    try {
      const data = await apiFetch(`/agent/conversations${path}`, { method: "POST", token, body, signal: request.signal })
      if (operation.current !== request || request.signal.aborted) return
      setView({ token, data }); setText("")
      if (conversationId === data.id) setReload(value => value + 1)
      else navigate(`/agent/${data.id}`)
    } catch (failure) {
      if (failure.name !== "AbortError") setError(failure.message)
    } finally {
      if (operation.current === request && !request.signal.aborted) setSubmittedAt(null)
    }
  }
  const running = busy || view?.status === "running"
  const progress = busy ? { started_at: submittedAt } : view?.progress
  const messages = view?.messages || []
  const timeline = <WorkTimeline key={`${view?.id || ""}-${view?.revision || 0}`}
    results={view?.results || []} running={running} progress={progress} status={view?.status} token={token} onError={setError} />
  const timelineAbove = !running && messages.length > 0 && messages[messages.length - 1].role !== "user"
  return <>
    <div className="page-head"><div><h1 className="page-title">업무 도우미</h1><p className="page-sub">메일과 문서 작업을 요청하고, 실행할 내용을 확인하세요.</p></div></div>
    <div className={`agent-layout${historyOpen ? " history-open" : ""}`}>
      <div className="history-backdrop" onClick={() => setHistoryOpen(false)} />
      <aside className="card agent-history" id="agent-history-drawer" aria-label="최근 대화"><h2 className="section-title">최근 대화</h2>
        {list.length === 0 && <p className="section-note">아직 대화가 없습니다.</p>}
        {list.map(item => <Link className={item.id === conversationId ? "agent-history-item active" : "agent-history-item"} to={`/agent/${item.id}`} key={item.id}
          onClick={() => setHistoryOpen(false)}>
          <span>{item.title}</span><small className={`s-${item.status}`}><i className="dot" />{STATUS[item.status] || item.status}</small></Link>)}
      </aside>
      <section className="agent-conversation" aria-label="업무 대화">
        <div className="chat-bar">
          <button type="button" className="icon-btn" aria-expanded={historyOpen} aria-controls="agent-history-drawer" onClick={() => setHistoryOpen(value => !value)}
            id="agent-history-toggle"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>대화 목록</button>
          <Link className="icon-btn" to="/agent"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>새 대화</Link>
        </div>
        {(error || readError) && <p className="form-error" role="alert">{error || readError} <button className="btn" onClick={() => setReload(value => value + 1)}>상태 다시 읽기</button></p>}
        {conversationId && !view && !error && !readError && <p role="status">대화를 읽고 있습니다…</p>}
        {!conversationId && <div className="agent-intro"><h2 className="section-title">어떤 업무를 도와드릴까요?</h2><p>예: “가상 거래처 메일을 찾아서 답장 후보를 확인해 줘.”</p><p className="section-note">회사 업무 메일·PI·PO·CI·PL을 다룹니다. 발송과 발급은 각각 확인 후 실행합니다.</p></div>}
        <div className="thread" ref={endRef}>
          {messages.map((message, index) => <Fragment key={index}>
            {timelineAbove && index === messages.length - 1 && timeline}
            {message.role === "user"
              ? <div className="msg-user">{message.text}</div>
              : <div className="msg-agent"><AssistantMarkdown text={message.text} /></div>}
          </Fragment>)}
          {view?.error && <p className="form-error" role="alert">{ERRORS[view.error] || `처리 상태를 확인해 주세요. (${view.error})`}</p>}
          {!timelineAbove && timeline}
          {view?.waiting && <ReviewCard key={`${view.revision}-${view.waiting.task_id || view.waiting.action?.id}`} waiting={view.waiting}
            piCompletion={view.waiting.fields?.includes("pi_changes") ? view.working?.data?.pi_completion : undefined}
            results={view.working?.data?.candidates ? [{ data: view.working.data }] : (view.results || [])} busy={running} onResume={response => send(`/${view.id}/resume`, { revision: view.revision, response })} />}
          {["interrupted", "review"].includes(view?.status) && <div className="card agent-recover">
            <p>{view.results?.some(item => item.status === "unknown" && item.domain === "calendar") || view.working?.action?.domain === "calendar"
              ? "Google 캘린더에서 해당 일정의 현재 상태를 조회합니다."
              : "실행이 중단되었거나 결과 확인이 필요합니다. 이미 보냈을 수 있는 메일은 자동으로 다시 보내지 않습니다."}</p>
            <button className="btn" disabled={running} onClick={() => send(`/${view.id}/recover`, { revision: view.revision })}>저장된 실행 상태 확인</button></div>}
        </div>
        <p className={progress ? "sr-only" : "runline"} role="status">{running ? "업무를 처리하고 있습니다." : view ? STATUS[view.status] : ""}</p>
        {(!conversationId || (view && !view.waiting && !running && !["interrupted", "review"].includes(view.status))) && <form className="card agent-compose" onSubmit={event => {
          event.preventDefault(); if (text.trim()) send(conversationId ? `/${conversationId}/messages` : "", { message: text.trim(), ...(view ? { revision: view.revision } : {}) })
        }}><label className="sr-only" htmlFor="agent-request">업무 요청</label><textarea id="agent-request" rows={4} maxLength={8000} value={text} onChange={event => setText(event.target.value)} disabled={running} required placeholder="메일이나 문서 작업을 요청해 주세요." />
          <button className="btn blue" type="submit" aria-label="요청하기" disabled={running || !text.trim()}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg><span>요청하기</span></button></form>}
      </section>
    </div>
  </>
}
