import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { apiFetch } from "../api"
import { useAuth } from "../useAuth"
import "./status.css"

// 작업현황: 메일(스레드별 최신 처리)·채팅 대화·무역 문서를 읽기 전용으로 합친 목록과 상세.
// 조회는 기록만 읽는다 — 이 화면을 열어도 그래프나 AI를 다시 실행하지 않는다(계획 17절).
// 상태·결과 어휘는 업무 도우미(AgentPage)와 같은 말을 쓴다.

const STATES = [
  { key: "running", label: "진행 중", dot: "run", hint: "실행 중인 작업" },
  { key: "needs_input", label: "답변 대기", dot: "wait", hint: "도우미 질문에 답할 차례" },
  { key: "needs_approval", label: "승인 대기", dot: "wait", hint: "후보·문서 승인을 기다림" },
  { key: "attention", label: "결과 확인 필요", dot: "bad", hint: "실패했거나 결과를 모름" },
]
const PILL = {
  running: { cls: "run", label: "진행 중" }, needs_input: { cls: "wait", label: "답변 대기" },
  needs_approval: { cls: "wait", label: "승인 대기" }, completed: { cls: "ok", label: "완료" },
  attention: { cls: "bad", label: "결과 확인 필요" }, skipped: { cls: "off", label: "처리 안 함" },
}
const KIND_LABEL = { mail: "받은 메일", chat: "업무 도우미", doc: "문서작성" }
const DOC_KIND = { PI: "견적 PI", PO: "주문서 PO", CI: "상업송장 CI", PL: "포장명세서 PL" }
const DOC_STEP = { needs_input: "남은 항목 입력", ready: "검토 대기", sent: "발급·발송 완료" }
const CHAT_STEP = { running: "업무 처리 중", needs_input: "질문에 답변하면 이어집니다", needs_approval: "승인을 기다립니다",
  completed: "응답 완료", error: "오류로 멈춤", interrupted: "실행 중단", review: "결과 확인 필요" }
const CANDIDATE = { pending: "승인 대기", approved: "보내는 중", sent: "보냄", send_failed: "보내기 실패",
  superseded: "다른 답장을 보냄" }
const OPERATIONS = { search: "메일 검색", query: "원문 조회", draft: "초안 작성", get: "문서 조회", schema: "입력 조건 확인",
  issue: "파일 발급", approve_packing: "포장 합계 승인", send: "답장 발송" }
const OUTCOMES = { completed: "완료", failed: "실패", cancelled: "취소", needs_review: "확인 필요", unknown: "결과 확인 필요",
  blocked: "선행 작업 확인 필요" }
const SRCS = [{ key: "all", label: "전체" }, { key: "mail", label: "메일" }, { key: "chat", label: "채팅" }, { key: "doc", label: "문서" }]

function relTime(iso) {
  if (!iso) return "-"
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return "방금 전"
  if (minutes < 60) return `${minutes}분 전`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}시간 전`
  if (minutes < 2880) return "어제"
  const date = new Date(iso)
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

function clock(iso) {
  if (!iso) return "-"
  const date = new Date(iso)
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
}

function duration(ms) {
  if (ms == null) return "-"
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}초`
  return `${Math.floor(seconds / 60)}분 ${seconds % 60}초`
}

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches

// 침 숫자는 처음 데이터가 도착했을 때만 올라가고, 이후 갱신은 즉시 바꾼다.
function CountUp({ to }) {
  const [value, setValue] = useState(0)
  const animated = useRef(false)
  useEffect(() => {
    if (animated.current) { setValue(to); return }
    animated.current = true
    if (reduced || !to) { setValue(to); return }
    const started = performance.now(), run = 550
    let raf
    const tick = now => {
      const p = Math.min(1, (now - started) / run), eased = 1 - Math.pow(1 - p, 3)
      setValue(Math.round(to * eased))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to])
  return <span className="num">{value}</span>
}

function Pill({ state }) {
  const pill = PILL[state] || PILL.attention
  return <span className={`st-pill p-${pill.cls}`}>{state === "running" ? <i className="spin" /> : <i />}{pill.label}</span>
}

// 상세의 실행 과정 한 단계: 펼치면 요약과 전체 값(raw)을 보여 준다.
function Step({ mark, name, at, body, raw, open: firstOpen }) {
  const [open, setOpen] = useState(Boolean(firstOpen))
  const icon = mark === "fail" ? <><path d="M12 8v5" /><path d="M12 16.5v.5" /><circle cx="12" cy="12" r="9" /></>
    : mark === "now" ? <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>
    : <path d="M20 6L9 17l-5-5" />
  return <li className={`st-ev ${mark || "done"}${open ? " open" : ""}`}>
    <button type="button" className="st-step-h" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <svg className="st-step-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icon}</svg>
      <span className="st-step-n">{name}</span>
      <span className="st-step-t num">{at}</span>
    </button>
    <div className="st-step-body">
      {body || "기록된 상세가 없습니다."}
      {raw && <pre>{raw}</pre>}
    </div>
  </li>
}

// 상세 본문: 소스별로 다른 실행 과정·만든 결과·AI 정보를 채운다.
function DetailBody({ task, token }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    const fail = () => setData({ error: true })
    if (task.kind === "mail" && task.run_id) {
      Promise.all([
        apiFetch(`/status/runs/${task.run_id}`, { token, signal: controller.signal }),
        apiFetch(`/mail/threads/${encodeURIComponent(task.thread_id)}`, { token, signal: controller.signal }).catch(() => null),
      ]).then(([run, thread]) => setData({ run, thread })).catch(fail)
    } else if (task.kind === "chat") {
      apiFetch(`/agent/conversations/${task.id}`, { token, signal: controller.signal }).then(view => setData({ view })).catch(fail)
    } else {
      setData({})
    }
    return () => controller.abort()
  }, [task.id, task.kind, task.run_id, task.thread_id, token])
  if (!data) return <p className="st-loading">상세를 불러오는 중입니다…</p>
  if (data.error) return <p className="st-loading">상세를 불러오지 못했습니다. 목록에서 다시 선택해 주세요.</p>

  const steps = []
  const results = []
  const ai = { model: null, calls: null, time: null, tokens: null }
  if (task.kind === "mail") {
    if (data.run) {
      data.run.events.forEach((event, index) => steps.push(
        <Step key={event.seq} mark={event.warn ? "fail" : index === data.run.events.length - 1 && task.state === "running" ? "now" : "done"}
          name={event.label} at={clock(event.at)} body={event.summary} raw={event.raw}
          open={index === data.run.events.length - 1} />))
      ai.calls = `${data.run.counts.llm}회`
      ai.time = duration(data.run.duration_ms)
    } else {
      steps.push(<Step key="excluded" name="메일 분류에서 제외" at={relTime(task.at)}
        body="업무 메일이 아니라고 분류되어 그래프를 실행하지 않았습니다." />)
    }
    data.thread?.candidates?.forEach(candidate => results.push(
      <div className="st-cand" key={candidate.id}><b>{candidate.label}</b>
        <small>{CANDIDATE[candidate.status] || candidate.status}</small></div>))
  } else if (task.kind === "chat") {
    const view = data.view
    view.results?.forEach(item => steps.push(
      <Step key={item.task_id} mark={item.status === "completed" ? "done" : item.status === "failed" ? "fail" : "now"}
        name={OPERATIONS[item.operation] || "업무 처리"}
        at={OUTCOMES[item.status] || "결과 확인 필요"}
        body={item.data ? JSON.stringify(item.data, null, 1) : null} />))
    const question = [...(view.messages || [])].reverse().find(message => message.role === "assistant")
    if (view.waiting && question) steps.push(
      <Step key="waiting" mark="now" name={task.raw_status === "needs_approval" ? "승인 대기" : "추가 질문"}
        at="대기 중" body={question.text} open />)
    if (view.error) steps.push(<Step key="error" mark="fail" name="오류" at="중단" body={view.error} />)
    view.results?.forEach(item => results.push(
      <div className="st-cand" key={item.task_id}><b>{OPERATIONS[item.operation] || "업무 처리"}</b>
        <small>{OUTCOMES[item.status] || "결과 확인 필요"}</small></div>))
  } else {
    steps.push(<Step key="doc" mark={task.state === "completed" ? "done" : "now"}
      name={DOC_STEP[task.raw_status] || "문서 상태 확인"} at={relTime(task.at)}
      body={task.state === "completed"
        ? "발급·발송이 끝난 문서입니다. 문서함에서 파일을 다시 내려받을 수 있습니다."
        : "직접 작성하는 문서라 실행 기록은 없습니다. 남은 항목을 입력하고 검토·발급으로 이어주세요."} />)
    results.push(<div className="st-cand" key={task.doc_no}><b>{task.doc_no}</b><small>버전 {task.revision}</small></div>)
  }

  return <>
    <section className="st-sec"><h3>실행 과정 <small>{steps.length ? `${steps.length}단계` : "없음"}</small></h3>
      {steps.length ? <ol className="st-steps">{steps}</ol> : <p className="st-loading">기록이 없습니다.</p>}
    </section>
    {results.length > 0 && <section className="st-sec"><h3>만든 결과 <small>{results.length}건</small></h3>{results}</section>}
    <section className="st-sec"><h3>AI 정보</h3>
      <dl className="st-kv">
        <dt>모델</dt><dd>{ai.model || <span className="dash">기록 없음</span>}</dd>
        <dt>모델 호출</dt><dd className="num">{ai.calls || <span className="dash">-</span>}</dd>
        <dt>처리 시간</dt><dd className="num">{ai.time || <span className="dash">-</span>}</dd>
        <dt>토큰 입력/출력</dt><dd className="num">{ai.tokens || <span className="dash">반환값 없음</span>}</dd>
      </dl>
    </section>
    <p className="st-note">이 화면을 열거나 새로고침해도 그래프나 AI를 다시 실행하지 않습니다. 기록만 읽습니다.</p>
  </>
}

// 소스·상태별 남은 조치 버튼. 없으면 안내 문구만.
function Actions({ task }) {
  const inbox = <Link className="st-btn ghost" to={`/inbox?thread=${encodeURIComponent(task.thread_id)}`}>메일함에서 원문 보기</Link>
  const runlog = task.run_id ? <a className="st-btn ghost" href={`/runs/${task.run_id}`}>실행 기록 보기</a> : null
  if (task.kind === "mail") {
    if (task.state === "needs_approval")
      return <><Link className="st-btn blue" to={`/inbox?thread=${encodeURIComponent(task.thread_id)}`}>답장 후보 승인하러 가기</Link>{inbox}</>
    if (task.state === "attention")
      return <>{task.run_id ? <a className="st-btn blue" href={`/runs/${task.run_id}`}>실행 기록에서 확인하기</a>
        : <Link className="st-btn blue" to={`/inbox?thread=${encodeURIComponent(task.thread_id)}`}>메일함에서 확인하기</Link>}{inbox}</>
    return <>{runlog}{inbox}</>
  }
  if (task.kind === "chat") {
    const label = task.state === "needs_input" ? "질문에 답변하기"
      : task.state === "needs_approval" ? "승인하러 가기" : "대화 열기"
    return <Link className="st-btn blue" to={`/agent/${task.id}`}>{label}</Link>
  }
  const to = `/trade/${task.doc_kind.toLowerCase()}/${task.doc_id}`
  const label = task.state === "needs_input" ? "이어서 작성하기" : task.state === "needs_approval" ? "검토·승인하러 가기" : "문서 열기"
  return <><Link className={task.state === "completed" ? "st-btn ghost" : "st-btn blue"} to={to}>{label}</Link>
    <Link className="st-btn ghost" to="/documents">문서함 열기</Link>
  </>
}

export default function StatusPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const [tasks, setTasks] = useState(null)
  const [phase, setPhase] = useState("loading")
  const [failure, setFailure] = useState("")
  const [stateF, setStateF] = useState("")
  const [srcF, setSrcF] = useState("all")
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [stamp, setStamp] = useState(null)
  const spin = useRef(null)

  const load = useCallback(async () => {
    setFailure("")
    try {
      const data = await apiFetch("/status/tasks", { token })
      setTasks(data.tasks)
      setPhase("ready")
      setStamp(new Date())
    } catch (error) {
      setPhase("error")
      setFailure(error.message)
    }
  }, [token])
  useEffect(() => { load() }, [load])

  // 진행 중이 있으면 15초마다 다시 읽는다(나머지는 새로고침 버튼으로).
  const running = useMemo(() => (tasks || []).some(task => task.state === "running"), [tasks])
  useEffect(() => {
    if (!running) return
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [running, load])

  const counts = useMemo(() => {
    const acc = { running: 0, needs_input: 0, needs_approval: 0, attention: 0, completed: 0, skipped: 0 }
    for (const task of tasks || []) acc[task.state] = (acc[task.state] || 0) + 1
    return acc
  }, [tasks])
  const attentionAll = counts.running + counts.needs_input + counts.needs_approval + counts.attention

  const rows = useMemo(() => (tasks || []).filter(task =>
    (!stateF || task.state === stateF) && (srcF === "all" || task.kind === srcF)
    && (!query || (task.title + (task.sub || "")).includes(query))), [tasks, stateF, srcF, query])

  const task = useMemo(() => (tasks || []).find(item => item.id === selected) || null, [tasks, selected])
  useEffect(() => { if (!task && rows.length) setSelected(rows[0].id) }, [task, rows])

  const subline = task => task.kind === "mail" ? `${KIND_LABEL.mail} · ${task.sub || "발신 정보 없음"}`
    : task.kind === "chat" ? KIND_LABEL.chat : `${KIND_LABEL.doc} · ${DOC_KIND[task.doc_kind] || task.doc_kind}`
  const stepline = task => task.kind === "mail"
    ? (PILL[task.state]?.label || "확인 필요") + (task.state === "needs_approval" ? " · 후보 승인" : "")
    : task.kind === "chat" ? CHAT_STEP[task.raw_status] || "상태 확인 필요" : DOC_STEP[task.raw_status] || "상태 확인 필요"

  const refresh = () => {
    if (!reduced && spin.current) spin.current.animate([{ transform: "rotate(0)" }, { transform: "rotate(360deg)" }], { duration: 400 })
    load()
  }

  if (phase === "loading") return <div className="st"><p className="st-boot">작업 목록을 불러오는 중입니다…</p></div>
  if (phase === "error") return <div className="st"><p className="st-boot" role="alert">{failure}</p>
    <button className="st-btn ghost" type="button" onClick={load}>다시 시도</button></div>

  const waiting = [counts.needs_approval, counts.needs_input].filter(Boolean)
  return <div className="st">
    <div className="st-head">
      <div>
        <h1 className="st-title">작업현황</h1>
        <p className="st-sub">
          {attentionAll > 0
            ? <>내가 확인할 일 <b className="num">{attentionAll}</b>건{waiting.length > 0 && <> · 그중 <b className="num">{waiting.reduce((a, b) => a + b, 0)}</b>건이 승인·답변을 기다립니다</>}</>
            : <>확인할 일이 없습니다. 최근 작업 <b className="num">{(tasks || []).length}</b>건을 지켜보고 있습니다.</>}
        </p>
      </div>
      <div className="st-fresh">
        <span>마지막 갱신 <span className="num">{stamp ? clock(stamp.toISOString()) : "-"}</span></span>
        <button className="st-refresh" type="button" onClick={refresh}>
          <svg ref={spin} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></svg>새로고침</button>
      </div>
    </div>

    <div className="st-chips" role="group" aria-label="상태별 보기">
      {STATES.map((state, index) =>
        <button key={state.key} type="button" className="st-chip" style={{ animationDelay: `${index * 60}ms` }}
          aria-pressed={stateF === state.key} data-on={stateF === state.key ? 1 : 0}
          onClick={() => setStateF(stateF === state.key ? "" : state.key)}>
          <span className="k"><i className={`dot ${state.dot}`} />{state.label}</span>
          <span className="v"><CountUp to={counts[state.key] || 0} /></span>
          <span className="hint">{state.hint}</span>
        </button>)}
    </div>

    <div className="st-bar">
      <div className="st-tabs" role="tablist">
        {SRCS.map(source => <button key={source.key} type="button" role="tab" className="st-tab"
          aria-selected={srcF === source.key} onClick={() => setSrcF(source.key)}>{source.label}</button>)}
      </div>
      <div className="st-toolbar">
        <span className="st-total num">{rows.length}건</span>
        <label className="st-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <input type="search" placeholder="업무 검색" aria-label="업무 검색" value={query}
            onChange={event => setQuery(event.target.value.trim())} />
        </label>
      </div>
    </div>

    <div className={`st-cols${detailOpen ? " show-detail" : ""}`}>
      <div className="st-list">
        <table>
          <thead><tr><th>업무</th><th style={{ textAlign: "right", paddingRight: 2 }}>상태</th>
            <th className="num" style={{ paddingRight: 14 }}>최근 변경</th></tr></thead>
          <tbody>
            {rows.map((row, index) => <tr key={row.id}><td colSpan={3} style={{ padding: 0 }}>
              <button type="button" className="st-row" style={{ animationDelay: `${Math.min(index * 45, 320)}ms` }}
                aria-pressed={row.id === selected}
                onClick={() => { setSelected(row.id); setDetailOpen(true) }}>
                <span className="top1">
                  <span className="st-name">{row.title}</span>
                  <Pill state={row.state} />
                  <span className="st-when num">{relTime(row.at)}</span>
                </span>
                <span className="top2">
                  <span className="st-via">{subline(row)}</span>
                  <span aria-hidden="true" className="sep">·</span>
                  <span className="st-step">{stepline(row)}</span>
                </span>
              </button>
            </td></tr>)}
          </tbody>
        </table>
        {rows.length === 0 && <p className="st-empty">조건에 맞는 작업이 없습니다. 필터를 바꿔 보세요.</p>}
      </div>

      <aside className="st-detail" aria-label="선택한 작업 상세">
        {!task ? <p className="st-loading">목록에서 작업을 선택하면 상세가 열립니다.</p> : <>
          <button className="st-back" type="button" onClick={() => setDetailOpen(false)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>목록으로</button>
          <div className="st-src">{subline(task)}</div>
          <h2 className="st-dtitle">{task.title}</h2>
          <div className="st-drow">
            <Pill state={task.state} />
            <span className="st-dwhen num">{relTime(task.at)} 변경</span>
          </div>
          <div className="st-act"><Actions task={task} /></div>
          <DetailBody key={task.id} task={task} token={token} />
        </>}
      </aside>
    </div>
  </div>
}
