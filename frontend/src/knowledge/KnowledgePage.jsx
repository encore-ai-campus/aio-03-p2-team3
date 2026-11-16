import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import "./knowledge.css"

const ROOT = "/knowledge/documents"
const ACTIVE = new Set(["queued", "extracting", "chunking", "embedding"])
const STATUS = { queued: "처리 대기", extracting: "페이지 읽는 중", needs_review: "원문 확인 필요", chunking: "청크 만드는 중", embedding: "임베딩 중", ready: "저장 완료", failed: "처리 실패" }
const WARNINGS = { converted_layout_requires_review: "변환한 페이지의 표·인쇄 영역·누락 여부를 원본과 비교해 주세요.", large_page_requires_review: "큰 페이지의 작은 글씨가 정확히 읽혔는지 확인해 주세요.", page_mapping_requires_review: "일부 페이지의 전사 순서 또는 누락을 확인해 주세요.", transcription_requires_review: "판독이 불확실한 부분을 원본과 비교해 수정해 주세요.", empty_transcription_requires_review: "읽은 원문이 없습니다. 원본을 확인하고 내용을 입력하거나 다시 추출해 주세요." }
const ERRORS = { LOCAL_KEY_REQUIRED: "로컬 .env에 OPENAI_API_KEY를 지정하고 앱을 다시 시작해 주세요.", LOCAL_RUNTIME_REQUIRED: "전용 로컬 실행 명령(uv run python -m app.local)으로 앱을 다시 시작해 주세요.", provider_rate_limit: "AI 사용 한도를 확인한 뒤 다시 시도해 주세요.", provider_access_denied: "설정에 등록한 키와 모델 이용 권한을 확인해 주세요.", LOCAL_WORKER_KEY_FORBIDDEN: "현재 개인 PC 실행 방식은 문서함의 이미지·임베딩 요청을 지원하지 않습니다.", OPENAI_KEY_REQUIRED: "설정에서 본인의 OpenAI 키를 등록해 주세요.", office_not_installed: "서버에 LibreOffice가 필요합니다. PDF로 변환해 올릴 수도 있습니다.", processing_interrupted: "처리가 중단되었습니다. 이전 저장 결과는 보존됩니다. 확인 후 다시 시도해 주세요.", hidden_sheet: "숨김 시트를 표시하거나 필요한 내용을 PDF로 내보내 주세요.", formula_cache_missing: "Excel에서 수식을 재계산·저장하거나 PDF로 내보내 주세요." }

function PagePreview({ id, number, token }) {
  const [preview, setPreview] = useState({ url: "", error: "" })
  useEffect(() => {
    const controller = new AbortController()
    let url
    setPreview({ url: "", error: "" })
    apiFetch(`${ROOT}/${id}/pages/${number}`, { token, signal: controller.signal, responseType: "blob" }).then((blob) => {
      if (controller.signal.aborted) return
      url = URL.createObjectURL(blob)
      setPreview({ url, error: "" })
    }).catch((error) => { if (!controller.signal.aborted) setPreview({ url: "", error: error.message }) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [id, number, token])
  return <div className="knowledge-preview">{preview.error ? <p role="alert">{preview.error}</p> : preview.url
    ? <a href={preview.url} target="_blank" rel="noreferrer" aria-label={`${number}페이지 크게 보기`}><img src={preview.url} alt={`원본에서 렌더링한 ${number}페이지`} /></a>
    : <p role="status">원본 페이지를 불러오는 중입니다…</p>}</div>
}

function OriginalPreview({ id, token }) {
  const [number, setNumber] = useState(1)
  const [preview, setPreview] = useState({ url: "", count: 1, error: "" })
  useEffect(() => {
    const controller = new AbortController()
    let url
    setPreview((previous) => ({ ...previous, url: "", error: "" }))
    apiFetch(`${ROOT}/${id}/pages/${number}`, { token, signal: controller.signal, responseType: "response" }).then(async (response) => {
      const blob = await response.blob()
      if (controller.signal.aborted) return
      url = URL.createObjectURL(blob)
      setPreview({ url, count: Number(response.headers.get("X-Page-Count")) || 1, error: "" })
    }).catch((error) => { if (!controller.signal.aborted) setPreview((previous) => ({ ...previous, error: error.message })) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [id, number, token])
  return <>
    <div className="knowledge-actions">
      <button className="btn" type="button" disabled={number <= 1} onClick={() => setNumber((value) => value - 1)}>원본 이전 페이지</button>
      <span role="status">원본 {number} / {preview.count}페이지</span>
      <button className="btn" type="button" disabled={!preview.url || number >= preview.count} onClick={() => setNumber((value) => value + 1)}>원본 다음 페이지</button>
    </div>
    {preview.error ? <p role="alert">{preview.error}</p> : preview.url
      ? <a href={preview.url} target="_blank" rel="noreferrer" aria-label={`원본 ${number}페이지 크게 보기`}><img className="knowledge-original-image" src={preview.url} alt={`업로드한 원본 ${number}페이지`} /></a>
      : <p role="status">원본을 불러오는 중입니다…</p>}
  </>
}

function ChunkViewer({ id, token }) {
  const [offset, setOffset] = useState(0)
  const [read, setRead] = useState({ data: null, error: "" })
  const [index, setIndex] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setRead({ data: null, error: "" })
    apiFetch(`${ROOT}/${id}/chunks?offset=${offset}`, { token, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) { setRead({ data, error: "" }); setIndex(0) }
    }).catch((error) => { if (!controller.signal.aborted) setRead({ data: null, error: error.message }) })
    return () => controller.abort()
  }, [id, token, offset])
  if (read.error) return <p role="alert">{read.error}</p>
  if (!read.data) return <p role="status">청크를 불러오는 중입니다…</p>
  const child = read.data.children[index]
  const parent = read.data.parents.find((value) => value.id === child?.parent_id)
  return <section className="knowledge-chunks" aria-label="저장한 부모와 자식 청크">
    <h3>저장한 청크</h3>
    <label className="field">자식 청크 선택<select value={index} onChange={(event) => setIndex(Number(event.target.value))}>
      {read.data.children.map((value, i) => <option key={value.id} value={i}>{value.ordinal + 1}. {value.text.slice(0, 60)}</option>)}
    </select></label>
    {child && <><p className="section-note">자식 {child.ordinal + 1} · 벡터 {child.dimensions}차원 · 부모 안 위치 {child.start}–{child.end}</p>
      <pre>{child.text}</pre><details><summary>연결한 부모 조항 원문 보기</summary>
        <p>{parent?.sources.map((source) => source.source).join(" · ")}</p><pre>{parent?.text}</pre>
      </details></>}
    <div className="knowledge-actions"><button className="btn" disabled={!offset} onClick={() => setOffset((value) => value - 50)}>이전 청크</button>
      <button className="btn" disabled={read.data.children.length < 50} onClick={() => setOffset((value) => value + 50)}>다음 청크</button></div>
  </section>
}

function DocumentDetail({ id, token, refresh, changed }) {
  const [read, setRead] = useState({ data: null, error: "" })
  const [editor, setEditor] = useState(null)
  const [number, setNumber] = useState(1)
  const [showOriginal, setShowOriginal] = useState(false)
  const [action, setAction] = useState({ busy: false, error: "", notice: "" })
  const dirty = useRef(false)
  const mutation = useRef(null)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    apiFetch(`${ROOT}/${id}`, { token, signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return
      setRead({ data, error: "" })
      if (!dirty.current) setEditor({ attempt_id: data.attempt_id, revision: data.revision,
        pages: data.pages.map((page) => ({ number: page.number, text: page.text })) })
    }).catch((error) => { if (!controller.signal.aborted) setRead((previous) => ({ ...previous, error: error.message })) })
    return () => controller.abort()
  }, [id, token, refresh, reload])
  useEffect(() => {
    if (!ACTIVE.has(read.data?.status)) return undefined
    const timer = setTimeout(() => setReload((value) => value + 1), 2000)
    return () => clearTimeout(timer)
  }, [read.data, reload])
  useEffect(() => () => mutation.current?.abort(), [])

  async function act(kind) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller
    setAction({ busy: true, error: "", notice: "" })
    try {
      const retry = kind === "retry"
      const data = await apiFetch(`${ROOT}/${id}/${retry ? "retry" : "extraction"}`, {
        method: retry ? "POST" : "PUT", token, signal: controller.signal,
        body: retry ? { attempt_id: read.data.attempt_id } : { ...editor, confirm: kind === "confirm" },
      })
      if (controller.signal.aborted) return
      dirty.current = false
      setRead((previous) => ({ ...previous, data: { ...previous.data, ...data } }))
      setAction({ busy: false, error: "", notice: kind === "save" ? "수정문을 저장했습니다. 확인 후 확정해 주세요." : "처리를 요청했습니다." })
      setReload((value) => value + 1)
      changed()
    } catch (error) {
      if (!controller.signal.aborted) setAction({ busy: false, notice: "", error: ERRORS[error.code] ?? (error.status === 409
        ? "서버의 원문 또는 상태가 바뀌었습니다. 입력은 보존했습니다. 다시 읽고 비교한 뒤 수정문을 적용해 주세요." : error.message) })
    } finally { if (mutation.current === controller) mutation.current = null }
  }

  const data = read.data
  const processing = ACTIVE.has(data?.status)
  const currentPage = data?.pages.find((page) => page.number === number)
  const editIndex = editor?.pages.findIndex((page) => page.number === number) ?? -1
  return <section className="card knowledge-detail" aria-label="문서 상세">
    {read.error && <p role="alert" className="form-error">{read.error}</p>}
    {!data ? !read.error && <p role="status">문서를 불러오는 중입니다…</p> : <>
      <div className="knowledge-detail-head"><div><h2>{data.filename}</h2><p role="status">{STATUS[data.status] ?? data.status}</p></div>
        <button className="btn" type="button" onClick={() => setReload((value) => value + 1)}>다시 읽기</button></div>
      <div className="knowledge-actions">
        <button className="btn" type="button" aria-expanded={showOriginal} aria-controls="document-original"
          onClick={() => setShowOriginal((shown) => !shown)}>{showOriginal ? "원본 미리보기 닫기" : "원본 보기"}</button>
        <button className="btn" type="button" disabled={action.busy} onClick={async () => {
        try { await downloadFile({ download_url: `/api${ROOT}/${id}/download`, filename: data.filename }, token) }
        catch (error) { setAction({ busy: false, error: error.message, notice: "" }) }
      }}>원본 다운로드</button>
        <button className="btn" type="button" disabled={processing || action.busy || dirty.current} onClick={() => act("retry")}>다시 추출·임베딩</button></div>
      {showOriginal && <section id="document-original" aria-label="업로드한 원본 미리보기">
        <h3>업로드한 원본</h3>
        <OriginalPreview key={id} id={id} token={token} />
      </section>}
      {data.error_code && <p role="alert" className="form-error">{ERRORS[data.error_code] ?? "처리에 실패했습니다. 원본과 모델 설정을 확인한 뒤 다시 시도해 주세요."} <small>({data.error_code})</small></p>}
      {data.published_attempt_id && data.published_attempt_id !== data.attempt_id && <p className="knowledge-note">이전에 저장한 인덱스를 보존하고 있습니다. 새 처리가 모두 성공하면 교체합니다.</p>}
      {data.warnings.map((warning) => <p key={warning} className="knowledge-note">{WARNINGS[warning] ?? "추출 결과를 원본과 대조해 주세요."}</p>)}
      {processing && <p className="section-note">이 화면은 처리 중에 자동으로 갱신됩니다. 업로드 완료와 임베딩 저장 완료는 별개입니다.</p>}
      {!!editor?.pages.length && <>
        <label className="field">대조할 페이지<select value={number} onChange={(event) => setNumber(Number(event.target.value))}>
          {data.pages.map((page) => <option key={page.number} value={page.number}>{page.source}</option>)}
        </select></label>
        <div className="knowledge-compare"><PagePreview id={id} number={number} token={token} />
          <div><label className="field" htmlFor="knowledge-text">추출문 · 원본과 비교해 수정하세요</label>
            <textarea id="knowledge-text" value={editor.pages[editIndex]?.text ?? ""} disabled={processing || action.busy} onChange={(event) => {
              dirty.current = true
              setEditor((previous) => ({ ...previous, pages: previous.pages.map((page) => page.number === number ? { ...page, text: event.target.value } : page) }))
              setAction({ busy: false, error: "", notice: "저장하지 않은 수정이 있습니다." })
            }} />
            {currentPage?.uncertain.map((value, i) => <p className="knowledge-note" key={i}>{value}</p>)}
            <details><summary>AI가 추출한 최초 문장 보기</summary><pre>{data.raw_pages.find((page) => page.number === number)?.text || "전사된 내용이 없습니다."}</pre></details>
          </div></div>
        <div className="knowledge-actions"><button className="btn" disabled={processing || action.busy} onClick={() => act("save")}>수정 저장</button>
          <button className="btn blue" disabled={processing || action.busy || !editor.pages.some((page) => page.text.trim())} onClick={() => act("confirm")}>원문 확정 후 임베딩</button>
          <button className="link-button" disabled={processing || action.busy} onClick={() => {
            dirty.current = false
            setEditor({ attempt_id: data.attempt_id, revision: data.revision, pages: data.pages.map((page) => ({ number: page.number, text: page.text })) })
            setAction({ busy: false, error: "", notice: "서버에 저장된 원문을 불러왔습니다." })
          }}>수정 초기화</button></div>
        <p className="section-note">확정하면 모든 페이지의 현재 수정문으로 청크와 벡터를 만듭니다. 다시 추출하면 새로운 비전 AI 요청이 발생합니다.</p>
      </>}
      {action.error && <p role="alert" className="form-error">{action.error}</p>}
      {action.notice && !(data.status === "failed" && action.notice === "처리를 요청했습니다.") && <p role="status">{action.notice}</p>}
      {data.published_attempt_id && <><p className="knowledge-note">부모 {data.parent_count}개 · 자식 {data.child_count}개 · 임베딩 {data.published_profile.embedding?.model} / {data.published_profile.embedding?.dimensions}차원</p>
        <ChunkViewer key={data.published_attempt_id} id={id} token={token} /></>}
      <details><summary>처리 모델과 출처 정보</summary><pre>{JSON.stringify(data.published_attempt_id ? data.published_profile : data.profile, null, 2)}</pre></details>
    </>}
  </section>
}

export default function KnowledgePage() {
  const { state } = useAuth()
  const token = state.accessToken
  const [params, setParams] = useSearchParams()
  const id = params.get("document") ?? ""
  const [read, setRead] = useState({ documents: [], error: "", loading: true })
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [uploads, setUploads] = useState([])
  const [busy, setBusy] = useState(false)
  const mutation = useRef(null)
  const files = useRef(null)
  useEffect(() => {
    const controller = new AbortController()
    apiFetch(`${ROOT}?offset=${offset}`, { token, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setRead({ ...data, error: "", loading: false })
    }).catch((error) => { if (!controller.signal.aborted) setRead((previous) => ({ ...previous, error: error.message, loading: false })) })
    return () => controller.abort()
  }, [token, refresh, offset])
  const processing = read.documents.some((document) => ACTIVE.has(document.status))
  useEffect(() => {
    if (!processing) return undefined
    const timer = setTimeout(() => setRefresh((value) => value + 1), 2000)
    return () => clearTimeout(timer)
  }, [processing, refresh])
  useEffect(() => () => mutation.current?.abort(), [])

  async function upload(event) {
    event.preventDefault()
    if (mutation.current) return
    const selected = Array.from(files.current.files)
    if (!selected.length) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true)
    setUploads(selected.map((file) => ({ name: file.name, message: "업로드 대기" })))
    let firstId
    for (const [index, file] of selected.entries()) {
      if (controller.signal.aborted) break
      let message, documentId
      try {
        if (file.size > 20 * 1024 * 1024) throw new Error("20MiB를 넘습니다. 파일을 나누어 주세요.")
        const form = new FormData()
        form.append("file", file)
        const data = await apiFetch(ROOT, { method: "POST", token, body: form, signal: controller.signal })
        documentId = data.id
        firstId ??= data.id
        message = data.duplicate ? "같은 원본이 등록되어 있습니다. 기존 처리 결과를 표시합니다." : "업로드 완료 · 처리 대기"
      } catch (error) { message = ERRORS[error.code] ?? error.message }
      if (!controller.signal.aborted) setUploads((previous) => previous.map((value, i) => i === index ? { ...value, id: documentId, message } : value))
    }
    if (!controller.signal.aborted) {
      if (firstId) setParams({ document: firstId })
      setOffset(0)
      setRefresh((value) => value + 1)
      setBusy(false)
    }
    if (mutation.current === controller) mutation.current = null
  }

  return <div className="knowledge-workspace">
    <div className="page-head"><div><h1 className="page-title">문서함</h1><p className="page-sub">문서를 업로드하고 저장한 원본과 처리 상태를 확인하세요.</p></div></div>
    <form className="card knowledge-upload" onSubmit={upload}>
      <label className="field" htmlFor="knowledge-files">문서 선택<input ref={files} id="knowledge-files" type="file" multiple required disabled={busy} accept=".pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg" /></label>
      <p className="section-note">PDF·DOCX·XLSX·TXT·PNG·JPEG · 파일당 20MiB · 변환 후 50페이지까지. HWP는 PDF로 변환해 주세요. 원본 페이지를 본인의 OpenAI 키로 전송해 읽습니다.</p>
      <button className="btn blue" disabled={busy} type="submit">{busy ? "업로드 중…" : "문서 업로드"}</button>
      {!!uploads.length && <ul aria-live="polite">{uploads.map((value, index) => <li key={index}>{value.name} — {STATUS[read.documents.find((document) => document.id === value.id)?.status] ?? value.message}</li>)}</ul>}
    </form>
    <div className="knowledge-layout"><section className="card knowledge-list" aria-label="내 문서 목록"><div className="knowledge-detail-head"><h2>업로드한 문서</h2><button className="link-button" onClick={() => setRefresh((value) => value + 1)}>새로고침</button></div>
      {read.error && <p role="alert" className="form-error">{read.error}</p>}
      {read.loading && <p role="status">목록을 불러오는 중입니다…</p>}
      {!read.loading && !read.documents.length && <p>등록된 문서가 없습니다.</p>}
      <ul>{read.documents.map((document) => <li key={document.id}><button type="button" className={id === document.id ? "selected" : ""} aria-pressed={id === document.id} onClick={() => setParams({ document: document.id })}>
        <strong>{document.filename}</strong><span>{STATUS[document.status] ?? document.status} · {(document.size_bytes / 1024 / 1024).toFixed(1)}MiB</span>
      </button></li>)}</ul>
      <div className="knowledge-actions"><button className="btn" disabled={!offset} onClick={() => setOffset((value) => value - 20)}>이전</button><button className="btn" disabled={read.documents.length < 20} onClick={() => setOffset((value) => value + 20)}>다음</button></div>
    </section>
      {id ? <DocumentDetail key={id} id={id} token={token} refresh={refresh} changed={() => setRefresh((value) => value + 1)} /> : <div className="card knowledge-empty"><h2>문서를 선택해 주세요</h2><p>업로드한 문서의 원본과 처리 결과를 확인할 수 있습니다.</p></div>}
    </div>
  </div>
}
