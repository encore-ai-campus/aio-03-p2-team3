import { Fragment, useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import ReviewCard from "./ReviewCard"
import Markdown from "react-markdown"
import remarkBreaks from "remark-breaks"
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
const OPERATIONS = { search: "메일 검색", query: "원문 조회", draft: "초안 작성", get: "문서 조회", schema: "입력 조건 확인",
  issue: "파일 발급", approve_packing: "포장 합계 승인", send: "답장 발송" }
const OUTCOMES = { completed: "완료", failed: "실패", cancelled: "취소", needs_review: "확인 필요", unknown: "결과 확인 필요", blocked: "선행 작업 확인 필요" }

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

function CopyButton({ text }) {
  const [done, setDone] = useState(false)
  return <button type="button" className="copy" onClick={() => {
    const finish = value => { setDone(value); if (value) setTimeout(() => setDone(false), 1400) }
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(() => finish(true), () => finish(false))
    else {
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      try { finish(document.execCommand("copy")) } catch { finish(false) }
      area.remove()
    }
  }}>{done ? "복사됨" : "복사"}</button>
}

function MarkdownText({ text }) {
  return <Markdown remarkPlugins={[remarkBreaks]} components={{
    a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    pre: ({ children }) => {
      const content = children?.props?.children
      const raw = Array.isArray(content) ? content.join("") : String(content ?? "")
      return <div className="codeblock"><CopyButton text={raw} /><pre>{children}</pre></div>
    },
  }}>{text}</Markdown>
}

function StepDetail({ item, token, onError }) {
  return <>
    {item.code && <p>{item.code}</p>}
    {item.data?.threads?.map(thread => <p key={thread.thread_id}><Link to={`/inbox?thread=${encodeURIComponent(thread.thread_id)}`}>{thread.subject}</Link> · {thread.from_addr}</p>)}
    {item.data?.messages?.map(message => <article key={message.gmail_message_id}><b>{message.subject}</b><p>{message.from_addr}</p>
      <p className="agent-text">{message.body_text}</p></article>)}
    {item.data?.candidates?.map(candidate => candidate && <article key={candidate.id} className="agent-candidate"><b>#{candidate.id} {candidate.label}</b>
      <p>{candidate.subject}</p><p className="agent-text">{candidate.body}</p></article>)}
    {item.data?.document_id && item.kind && <p><Link to={`/trade/${item.kind.toLowerCase()}/${item.data.document_id}`}>{item.kind} 문서 #{item.data.document_id} 열기</Link></p>}
    {item.data?.sent_message_id && <p role="status">메일을 보냈습니다.</p>}
    {item.data?.files?.map(file => <button className="btn" key={file.id} onClick={() => downloadFile(file, token).catch(error => onError(error.message))}>{file.filename} 다운로드</button>)}
    {item.operation === "schema" && <p>문서 작성에 필요한 입력 조건을 확인했습니다.</p>}
    {!item.data?.threads && !item.data?.messages && !item.data?.candidates && !item.data?.files && item.operation !== "schema" &&
      <pre>{JSON.stringify(item.data, null, 2)}</pre>}
  </>
}

function Step({ item, token, onError, dim }) {
  const [open, setOpen] = useState(false)
  const label = OPERATIONS[item.operation] || "업무 처리"
  const outcome = OUTCOMES[item.status] || "결과 확인 필요"
  return <li className={`step${open ? " open" : ""}${dim ? " dim" : ""}`}>
    <button type="button" className="step-head" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Icon name={item.operation} />
      <span className="step-name">{label}</span>
      <span className="step-sep" aria-hidden="true"> · </span>
      <span className={`step-outcome ${item.status}`}>{outcome}</span>
      <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
    </button>
    <div className="step-body"><div><div className="step-detail"><StepDetail item={item} token={token} onError={onError} /></div></div></div>
  </li>
}

function WorkTimeline({ results, running, token, onError }) {
  const [open, setOpen] = useState(false)
  const wasRunning = useRef(false)
  useEffect(() => {
    if (running) { setOpen(true); wasRunning.current = true }
    else if (wasRunning.current) { setOpen(false); wasRunning.current = false }
  }, [running])
  if (!results.length) return null
  const attention = results.some(item => item.status !== "completed")
  const names = results.map(item => OPERATIONS[item.operation] || "업무 처리").slice(0, 3).join(" · ") + (results.length > 3 ? ` 외 ${results.length - 3}` : "")
  return <div className={`work${open ? " open" : ""}${running ? " running" : ""}`}>
    <button type="button" className="work-row" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      {running
        ? <span className="work-state" key="run"><svg className="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9" /></svg>업무 처리 중 · {results.length}단계</span>
        : attention
          ? <span className="work-state warn" key="warn"><svg className="ok-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 16.5v.5" /><circle cx="12" cy="12" r="9" /></svg>확인 필요 · {results.length}단계</span>
          : <span className="work-state" key="ok"><svg className="ok-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>업무 완료 · {results.length}단계</span>}
      <span className="work-meta">{names}</span>
    </button>
    <div className="work-body"><div><ol>
      {results.map((item, index) => <Step key={item.task_id || index} item={item} token={token} onError={onError} dim={running && index < results.length - 1} />)}
    </ol></div></div>
  </div>
}

export default function AgentPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const { conversationId = "" } = useParams()
  const navigate = useNavigate()
  const [list, setList] = useState([])
  const [view, setView] = useState(null)
  const [text, setText] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
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
    setView(null); setError(""); setText(""); setBusy(false)
    operation.current?.abort()
    async function read() {
      clearTimeout(timer)
      if (!conversationId || document.hidden) return
      request?.abort(); request = new AbortController()
      try {
        const data = await apiFetch(`/agent/conversations/${conversationId}`, { token, signal: request.signal })
        if (cancelled) return
        setView(data)
        setList(items => [{ id: data.id, title: data.title, status: data.status }, ...items.filter(item => item.id !== data.id)])
        if (data.status === "running") timer = setTimeout(read, 2000)
      } catch (failure) {
        if (!cancelled && failure.name !== "AbortError") setError(failure.message)
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
    setBusy(true); setError("")
    try {
      const data = await apiFetch(`/agent/conversations${path}`, { method: "POST", token, body, signal: request.signal })
      if (operation.current !== request || request.signal.aborted) return
      setText(""); navigate(`/agent/${data.id}`); setReload(value => value + 1)
    } catch (failure) {
      if (failure.name !== "AbortError") setError(failure.message)
    } finally {
      if (operation.current === request && !request.signal.aborted) setBusy(false)
    }
  }
  const running = busy || view?.status === "running"
  const messages = view?.messages || []
  const timeline = view && <WorkTimeline results={view.results || []} running={running} token={token} onError={setError} />
  const timelineAbove = messages.length > 0 && messages[messages.length - 1].role !== "user"
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
        {error && <p className="form-error" role="alert">{error} <button className="btn" onClick={() => setReload(value => value + 1)}>상태 다시 읽기</button></p>}
        {conversationId && !view && !error && <p role="status">대화를 읽고 있습니다…</p>}
        {!conversationId && <div className="agent-intro"><h2 className="section-title">어떤 업무를 도와드릴까요?</h2><p>예: “가상 거래처 메일을 찾아서 답장 후보를 확인해 줘.”</p><p className="section-note">회사 업무 메일·PI·PO·CI·PL을 다룹니다. 발송과 발급은 각각 확인 후 실행합니다.</p></div>}
        <div className="thread" ref={endRef}>
          {messages.map((message, index) => <Fragment key={index}>
            {timelineAbove && index === messages.length - 1 && timeline}
            {message.role === "user"
              ? <div className="msg-user">{message.text}</div>
              : <div className="msg-agent"><MarkdownText text={message.text} /></div>}
          </Fragment>)}
          {view?.error && <p className="form-error" role="alert">{ERRORS[view.error] || `처리 상태를 확인해 주세요. (${view.error})`}</p>}
          {!timelineAbove && timeline}
          {view?.waiting && <ReviewCard key={`${view.revision}-${view.waiting.task_id || view.waiting.action?.id}`} waiting={view.waiting}
            results={view.results || []} busy={running} onResume={response => send(`/${view.id}/resume`, { revision: view.revision, response })} />}
          {["interrupted", "review"].includes(view?.status) && <div className="card agent-recover"><p>실행이 중단되었거나 결과 확인이 필요합니다. 이미 보냈을 수 있는 메일은 자동으로 다시 보내지 않습니다.</p>
            <button className="btn" disabled={running} onClick={() => send(`/${view.id}/recover`, { revision: view.revision })}>저장된 실행 상태 확인</button></div>}
        </div>
        <p className={`runline${running ? " on" : ""}`} role="status" aria-live="polite">{running ? "업무를 처리하고 있습니다. 이 화면을 나가도 접수된 작업은 계속됩니다." : view ? STATUS[view.status] : ""}</p>
        {(!conversationId || (view && !view.waiting && !running && !["interrupted", "review"].includes(view.status))) && <form className="card agent-compose" onSubmit={event => {
          event.preventDefault(); if (text.trim()) send(conversationId ? `/${conversationId}/messages` : "", { message: text.trim(), ...(view ? { revision: view.revision } : {}) })
        }}><label className="sr-only" htmlFor="agent-request">업무 요청</label><textarea id="agent-request" rows={4} maxLength={8000} value={text} onChange={event => setText(event.target.value)} disabled={running} required placeholder="메일이나 문서 작업을 요청해 주세요." />
          <button className="btn blue" type="submit" aria-label="요청하기" disabled={running || !text.trim()}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg><span>요청하기</span></button></form>}
      </section>
    </div>
  </>
}
