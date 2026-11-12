import { useEffect, useEffectEvent, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import AIInput from "../trade/AIInput"
import DocumentSnapshot from "../trade/DocumentSnapshot"
import PIForm from "../trade/PIForm"
import { emptyPI, piDraft, piPayload } from "../trade/pi-input"
import ReviewPanel from "../trade/ReviewPanel"

const STATUS = { needs_input: "입력 필요", ready: "검토 가능", issued: "발급 완료" }

export default function PIPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const { documentId } = useParams()
  const navigate = useNavigate()
  const [resource, setResource] = useState(null)
  const [draft, setDraft] = useState(emptyPI)
  const [proposal, setProposal] = useState(null)
  const [formats, setFormats] = useState(["pdf", "xlsx"])
  const [dirty, setDirty] = useState(false)
  const [modifying, setModifying] = useState(false)
  const [loading, setLoading] = useState(Boolean(documentId))
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState("")
  const mutation = useRef(null)
  const base = "/trade/pi"

  function accept(document, review = null) {
    setResource(document)
    setDraft(piDraft(document.input))
    setProposal(review)
    if (review) setFormats(review.payload.formats)
    setDirty(false)
    setModifying(false)
  }

  // 같은 사용자의 토큰 갱신으로 저장 전 입력을 다시 읽어 덮어쓰지 않는다.
  const read = useEffectEvent(async (id, signal) => {
    const document = await apiFetch(`${base}/${id}`, { token, signal })
    const review = document.proposal_id
      ? await apiFetch(`${base}/${id}/reviews/${document.proposal_id}`, { token, signal }) : null
    if (!signal.aborted) accept(document, review)
  })
  useEffect(() => {
    const controller = new AbortController()
    mutation.current?.abort()
    mutation.current = null
    setBusy(false)
    setError(null)
    setNotice("")
    setResource(null)
    setProposal(null)
    setModifying(false)
    setDirty(false)
    if (!documentId) {
      setDraft(emptyPI())
      setLoading(false)
    } else {
      setLoading(true)
      read(documentId, controller.signal).catch((failure) => {
        if (!controller.signal.aborted) setError(failure)
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }
    return () => { controller.abort(); mutation.current?.abort() }
  }, [documentId, reload])

  async function perform(work, success) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true)
    setError(null)
    setNotice("")
    try {
      const result = await work(controller.signal)
      if (!controller.signal.aborted) success?.(result)
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure)
    } finally {
      if (mutation.current === controller) {
        mutation.current = null
        setBusy(false)
      }
    }
  }

  function save() {
    perform(async (signal) => {
      if (modifying) {
        const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
          token, signal, method: "POST", body: { action: "modify", revision: proposal.revision,
            content_hash: proposal.content_hash, document: piPayload(draft) } })
        if (review.document_type) return { document: review, review: null }
        const document = await apiFetch(`${base}/${resource.document_id}`, { token, signal })
        return { document, review }
      }
      const document = await apiFetch(resource ? `${base}/${resource.document_id}` : base, {
        token, signal, method: resource ? "PUT" : "POST",
        body: resource ? { revision: resource.revision, document: piPayload(draft) } : piPayload(draft) })
      return { document, review: null }
    }, ({ document, review }) => {
      accept(document, review)
      if (!documentId) navigate(`/trade/pi/${document.document_id}`, { replace: true })
      else setNotice("저장했습니다. 서버가 계산한 내용과 누락 항목을 확인해 주세요.")
    })
  }

  function propose() {
    perform((signal) => apiFetch(`${base}/${resource.document_id}/reviews`, { token, signal,
      method: "POST", body: { revision: resource.revision, formats } }), (review) => {
      setProposal(review)
      setNotice("최종 검토를 만들었습니다. 회사·계좌·직인과 금액을 확인하고 선택해 주세요.")
    })
  }

  function decide(action) {
    perform(async (signal) => {
      const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
        token, signal, method: "POST", body: { action, revision: proposal.revision, content_hash: proposal.content_hash } })
      const document = await apiFetch(`${base}/${resource.document_id}`, { token, signal })
      return { document, review }
    }, ({ document, review }) => {
      accept(document, review)
      setNotice(action === "approve" ? "파일을 발급했습니다. 아래에서 다운로드하세요. 메일은 발송하지 않았습니다." : "검토를 취소했습니다. 내용을 저장한 뒤 다시 검토할 수 있습니다.")
    })
  }

  const current = resource && String(resource.document_id) === documentId ? resource : null
  const pending = proposal?.status === "pending"
  const canEdit = !busy && !loading && (!documentId || current)
  return <>
    <div className="page-head"><div><h1 className="page-title">PI 작성</h1><p className="page-sub">직접 입력하거나 문장에서 초안을 만든 뒤, 확인한 버전으로 파일을 발급합니다.</p></div><Link className="btn" to="/">문서 종류 선택</Link></div>
    <div className="editor-toolbar"><span className="document-status">{current ? `${STATUS[current.status] ?? current.status} · 버전 ${current.revision} · 문서 ${current.document_id}` : "새 PI"}</span>
      {documentId && <button type="button" className="btn" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>최신본 다시 읽기</button>}
    </div>
    {error && <div className="settings-load-error" role="alert"><p>{error.status === 401 ? "로그인 확인이 필요합니다. 입력 내용을 별도로 보관한 뒤 다시 로그인해 주세요." : error.message}</p>
      {error.status === 409 && <p>최신본을 다시 읽고 새로 검토해 주세요. 다시 읽으면 현재 입력을 교체하므로, 필요한 내용은 먼저 복사해 두세요.</p>}</div>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {loading && <p role="status">PI와 검토 내용을 불러오는 중입니다…</p>}
    {!loading && (!documentId || current) && <div className="pi-editor">
      <AIInput token={token} disabled={busy || dirty || modifying} onExtract={(text) => perform((signal) => apiFetch(`${base}/extract`, {
        token, signal, method: "POST", body: { text } }), (document) => {
        accept(document)
        navigate(`/trade/pi/${document.document_id}`)
      })} />
      <section className="card editor-form" aria-label="PI 입력">
        <div className="panel-head"><h2 className="section-title">거래 내용</h2>{dirty && <span className="unsaved">저장 전 변경사항</span>}</div>
        {current?.status === "issued" && <p className="section-note">수정 저장하면 새 버전으로 바뀝니다. 이미 발급된 파일은 그대로 보존합니다.</p>}
        <PIForm draft={draft} setDraft={setDraft} missing={current?.missing_fields} disabled={!canEdit} onDirty={() => setDirty(true)} />
        <div className="form-actions"><button className="btn blue" type="button" disabled={!canEdit || (current && !dirty && !modifying)} onClick={save}>{busy ? "처리 중…" : modifying ? "수정 저장·재검토" : "초안 저장"}</button></div>
      </section>
      {current && <section className="card" aria-label="서버 계산 결과"><h2 className="section-title">저장된 내용 · 서버 계산 결과</h2>
        {current.missing_fields.length > 0 && <p className="form-error">입력이 필요한 항목: {current.missing_fields.join(" · ")}</p>}
        {current.issues.length > 0 && <ul className="document-issues">{current.issues.map((issue,index) => <li key={index}>{issue.message}</li>)}</ul>}
        <DocumentSnapshot document={current.document} />
        <fieldset className="editor-checks" disabled={busy || pending || current.status !== "ready"}><legend>발급 형식</legend>{["pdf","xlsx"].map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={(event) => setFormats((previous) => event.target.checked ? [...previous, format] : previous.filter((value) => value !== format))} /> {format.toUpperCase()}</label>)}</fieldset>
        <div className="form-actions"><button className="btn blue" type="button" disabled={busy || dirty || modifying || pending || current.status !== "ready" || !formats.length} onClick={propose}>최종 검토 만들기</button></div>
      </section>}
      {proposal && <ReviewPanel proposal={proposal} token={token} busy={busy} dirty={dirty} modifying={modifying}
        onDecision={decide} onModify={() => { setModifying(true); setNotice("거래 내용을 수정한 뒤 수정 저장·재검토를 눌러 주세요.") }}
        onDownload={(file) => perform((signal) => downloadFile(file, token, signal), () => setNotice("파일 다운로드를 요청했습니다."))} />}
    </div>}
  </>
}
