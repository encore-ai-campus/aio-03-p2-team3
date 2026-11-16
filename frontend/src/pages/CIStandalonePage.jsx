import { useEffect, useEffectEvent, useRef, useState } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import PIForm from "../trade/PIForm"
import CIForm from "../trade/CIForm"
import DocumentSnapshot from "../trade/DocumentSnapshot"
import ReviewPanel from "../trade/ReviewPanel"
import AIInput from "../trade/AIInput"
import { emptyPI, piDraft, piPayload } from "../trade/pi-input"
import { standaloneCINext } from "../trade/ci-input"

const steps = [["buyer", "거래처"], ["seller", "판매자"], ["items", "품목"], ["terms", "거래·선적 조건"]]
const base = "/trade/ci"
const statuses = { needs_input: "입력 필요", ready: "검토 가능", issued: "발급 완료" }

function payload(draft) {
  const values = piPayload(draft)
  delete values.payment_terms
  values.items.forEach((item) => { delete item.is_sample })
  return { ...values, mode: "standalone" }
}

export default function CIStandalonePage() {
  const { state } = useAuth()
  return <StandaloneEditor key={state.me?.user_id} />
}

function StandaloneEditor() {
  const { state } = useAuth()
  const token = state.accessToken
  const { documentId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [draft, setDraft] = useState(emptyPI)
  const [resource, setResource] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [settings, setSettings] = useState(null)
  const [settingsError, setSettingsError] = useState("")
  const [screen, setScreen] = useState("buyer")
  const [guided, setGuided] = useState(false)
  const [fields, setFields] = useState(null)
  const [formats, setFormats] = useState(["pdf", "xlsx"])
  const [dirty, setDirty] = useState(false)
  const [modifying, setModifying] = useState(false)
  const [loading, setLoading] = useState(Boolean(documentId))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState("")
  const [reload, setReload] = useState(0)
  const mutation = useRef(null)
  const created = useRef(null)

  function accept(document, review = null, next = "review") {
    setResource(document)
    setDraft(piDraft(document.input))
    setProposal(review)
    if (review) setFormats(review.payload.formats)
    setDirty(false)
    setModifying(false)
    setScreen(next)
  }

  const read = useEffectEvent(async (id, signal) => {
    const document = await apiFetch(`${base}/${id}`, { token, signal })
    if (document.input.mode !== "standalone") { navigate(`/trade/ci/${id}`, { replace: true }); return }
    const review = document.proposal_id ? await apiFetch(`${base}/${id}/reviews/${document.proposal_id}`, { token, signal }) : null
    if (!signal.aborted) accept(document, review)
  })
  useEffect(() => {
    const controller = new AbortController()
    if (created.current === documentId) {
      created.current = null
      return () => { controller.abort(); mutation.current?.abort() }
    }
    mutation.current?.abort()
    mutation.current = null
    setBusy(false); setError(null); setNotice(""); setResource(null); setProposal(null); setDirty(false); setModifying(false)
    if (!documentId) { setDraft(emptyPI()); setScreen(location.state?.source ? "source" : "buyer"); setGuided(false); setFields(null); setLoading(false) }
    else {
      setLoading(true)
      read(documentId, controller.signal).catch((failure) => { if (!controller.signal.aborted) setError(failure) })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }
    return () => { controller.abort(); mutation.current?.abort() }
  }, [documentId, reload, location.state?.source])

  useEffect(() => {
    const controller = new AbortController()
    apiFetch("/trade/settings", { token, signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return
      setSettings(data); setSettingsError("")
      if (!documentId) {
        const company = data.company ?? {}
        setDraft((previous) => ({ ...previous, seller: {
          ...Object.fromEntries(["address", "contact", "phone", "email", "registration_details"].map((key) => [key, previous.seller[key] || company[key] || ""])),
          legal_name: previous.seller.legal_name || company.legal_name_en || company.company_name || "",
        } }))
      }
    }).catch((failure) => { if (!controller.signal.aborted) setSettingsError(failure.message) })
    return () => controller.abort()
  }, [token, documentId])

  async function perform(work, success) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller; setBusy(true); setError(null); setNotice("")
    try { const result = await work(controller.signal); if (!controller.signal.aborted) success(result) }
    catch (failure) { if (!controller.signal.aborted) setError(failure) }
    finally { if (mutation.current === controller) { mutation.current = null; setBusy(false) } }
  }

  function edit(key) {
    if (proposal?.status === "pending") setModifying(true)
    setFields(null); setScreen(key)
  }
  function save() {
    perform(async (signal) => {
      if (modifying) {
        const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, { token, signal, method: "POST",
          body: { action: "modify", revision: proposal.revision, content_hash: proposal.content_hash, document: payload(draft) } })
        if (review.document_type) return { document: review, review: null }
        return { document: await apiFetch(`${base}/${resource.document_id}`, { token, signal }), review }
      }
      const document = await apiFetch(resource ? `${base}/${resource.document_id}` : base, { token, signal, method: resource ? "PUT" : "POST",
        body: resource ? { revision: resource.revision, document: payload(draft) } : payload(draft) })
      return { document, review: null }
    }, ({ document, review }) => {
      accept(document, review)
      if (!documentId) navigate(`/trade/ci/standalone/${document.document_id}`, { replace: true })
      else setNotice("저장했습니다. 계산된 금액과 전체 내용을 확인해 주세요.")
    })
  }
  function extract(text) {
    perform((signal) => apiFetch(`${base}/extract-standalone`, { token, signal, method: "POST", body: { text } }), (document) => {
      const next = standaloneCINext(piDraft(document.input))
      setGuided(true); setFields(next.fields)
      accept(document, null, next.key)
      created.current = String(document.document_id)
      navigate(`/trade/ci/standalone/${document.document_id}`, { replace: true })
    })
  }
  function propose() {
    perform((signal) => apiFetch(`${base}/${resource.document_id}/reviews`, { token, signal, method: "POST", body: { revision: resource.revision, formats } }),
      (review) => { setProposal(review); setNotice("최종 검토 내용을 확인해 주세요.") })
  }
  function decide(action) {
    perform(async (signal) => {
      const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, { token, signal, method: "POST",
        body: { action, revision: proposal.revision, content_hash: proposal.content_hash } })
      return { document: await apiFetch(`${base}/${resource.document_id}`, { token, signal }), review }
    }, ({ document, review }) => { accept(document, review); setNotice(action === "approve" ? "파일을 발급했습니다." : "검토를 취소했습니다.") })
  }

  const current = resource && String(resource.document_id) === documentId ? resource : null
  const enabled = !busy && !loading && (!documentId || current)
  const index = steps.findIndex(([key]) => key === screen)
  const nextStep = guided && index >= 0 ? standaloneCINext(draft, index).key : steps[index + 1]?.[0] ?? "review"
  const finalReview = proposal && ["pending", "approved"].includes(proposal.status) && !dirty && !modifying
  return <div className="pi-workspace">
    <div className="page-head"><div><h1 className="page-title">CI 직접 작성</h1><p className="page-sub">PI 없이 거래 내용과 선적 정보를 직접 입력합니다.</p></div><Link className="btn" to="/trade/ci">CI 작성 방법 선택</Link></div>
    <div className="editor-toolbar"><span className="document-status">{current ? `${statuses[current.status] ?? current.status} · 버전 ${current.revision}` : "새 CI"}</span>
      {documentId && <button className="btn" type="button" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>최신본 다시 읽기</button>}</div>
    {error && <div className="settings-load-error" role="alert"><p>{error.message}</p>{error.status === 409 && <p>최신본을 다시 읽으면 현재 입력이 교체됩니다. 필요한 내용은 먼저 복사해 두세요.</p>}</div>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {settingsError && <p className="section-note" role="status">기본 설정을 불러오지 못했습니다. 직접 입력할 수 있습니다. {settingsError}</p>}
    {loading && <p role="status">CI를 불러오는 중입니다.</p>}
    {!loading && (!documentId || current) && <>
      {screen !== "source" && <nav className="pi-progress" aria-label="CI 작성 단계"><ol>{steps.map(([key, label]) => <li key={key}><button type="button" disabled={!enabled} aria-current={screen === key ? "step" : undefined} onClick={() => edit(key)}>{label}</button></li>)}
        <li><button type="button" disabled={!enabled || !current || dirty || modifying} aria-current={screen === "review" ? "step" : undefined} onClick={() => setScreen("review")}>전체 확인</button></li></ol></nav>}
      <div className="pi-editor"><div className="pi-main">
        {screen === "source" && <><button className="pi-text-button" type="button" disabled={busy} onClick={() => navigate("/trade/ci")}>← 작성 방법 선택</button>
          <AIInput kind="CI" token={token} disabled={!enabled} onExtract={extract} /></>}
        {index >= 0 && <form className="pi-question" onSubmit={(event) => { event.preventDefault(); const next = guided ? standaloneCINext(draft, index) : { key: steps[index + 1]?.[0] ?? "review", fields: null }; if (next.key === "review") { if (!current || dirty || modifying) save(); else setScreen("review") } else { setFields(next.fields); setScreen(next.key) } }}>
          <h2>{steps[index][1]} 입력</h2>
          {fields && <><p className="pi-question-note">이미 채워진 내용은 보관했어요. 아래 빈칸만 알려주세요.</p><button className="pi-text-button" type="button" onClick={() => setFields(null)}>이 단계 전체 수정</button></>}
          {dirty && <p className="unsaved" role="status">저장하지 않은 변경사항이 있어요.</p>}
          {screen === "terms" ? <>
            <div className="settings-fields">{(!fields || fields.includes("product_family")) && <div className="field"><label htmlFor="ci-family">상품군</label><select id="ci-family" value={draft.product_family ?? ""} disabled={!enabled} onChange={(event) => { setDirty(true); setDraft((value) => ({ ...value, product_family: event.target.value })) }}>
              {[["other","기타"],["cosmetics","화장품"],["polysilicon","폴리실리콘"],["wafer","웨이퍼"],["solar_cell","태양전지"],["solar_module","태양광 모듈"]].map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></div>}
              {(!fields || fields.includes("currency")) && <div className="field"><label htmlFor="ci-currency">통화</label><input id="ci-currency" value={draft.currency ?? ""} maxLength={3} disabled={!enabled} onChange={(event) => { setDirty(true); setDraft((value) => ({ ...value, currency: event.target.value.toUpperCase(), items: value.items.map((item) => ({ ...item, confirm_price_override: false })) })) }} /></div>}</div>
            <CIForm standalone draft={draft} setDraft={setDraft} disabled={!enabled} onDirty={() => setDirty(true)} missing={fields ?? current?.missing_fields} onlyMissing={Boolean(fields)} />
          </> : <PIForm kind="ci" step={screen} fields={fields} draft={draft} setDraft={setDraft} settings={settings} disabled={!enabled} missing={current?.missing_fields} onDirty={() => setDirty(true)} onShowAll={() => setFields(null)} />}
          <div className="pi-step-actions"><button className="btn" type="button" disabled={!enabled} onClick={() => index ? setScreen(steps[index - 1][0]) : navigate("/trade/ci")}>이전</button>
            <button className="btn" type="button" disabled={!enabled || (current && !dirty && !modifying)} onClick={save}>임시 저장</button>
            <button className="btn blue" type="submit" disabled={!enabled}>{nextStep === "review" ? "저장하고 전체 확인" : "다음"}</button></div>
        </form>}
        {screen === "review" && current && (finalReview ? <ReviewPanel kind="ci" proposal={proposal} token={token} busy={busy} dirty={dirty} modifying={modifying} onDecision={decide} onModify={() => edit("buyer")}
          onDownload={(file) => perform((signal) => downloadFile(file, token, signal), () => setNotice("파일 다운로드를 요청했습니다."))} /> :
          <section className="pi-question"><h2>전체 내용을 확인해 주세요</h2>
            {current.issues.length > 0 && <ul className="document-issues">{current.issues.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul>}
            {current.missing_fields.length > 0 && <p className="form-error">보완할 항목: {current.missing_fields.join(", ")}</p>}
            <DocumentSnapshot kind="ci" document={current.document} />
            <fieldset className="editor-checks" disabled={busy || current.status !== "ready"}><legend>발급 형식</legend>{["pdf", "xlsx"].map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={(event) => setFormats((previous) => event.target.checked ? [...previous, format] : previous.filter((value) => value !== format))} /> {format.toUpperCase()}</label>)}</fieldset>
            <div className="form-actions"><button className="btn blue" type="button" disabled={busy || dirty || modifying || current.status !== "ready" || !formats.length} onClick={propose}>최종 검토 만들기</button></div>
          </section>)}
      </div></div>
    </>}
  </div>
}
