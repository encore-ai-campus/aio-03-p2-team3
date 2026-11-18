import { useEffect, useId, useRef, useState } from "react"
import { apiFetch } from "../api"

export default function AIInput({ token, disabled, onExtract, headingRef, kind = "PI", value, onTextChange, extractDisabled = false }) {
  const [text, setText] = useState("")
  const [keyState, setKeyState] = useState({ busy: false, error: "", notice: "" })
  const [fileState, setFileState] = useState({ busy: false, error: "", notice: "" })
  const keyRequest = useRef(null)
  const fileRequest = useRef(null)
  const textId = useId()
  const keyId = useId()
  const fileId = useId()
  const sourceText = value ?? text
  useEffect(() => () => {
    keyRequest.current?.abort()
    fileRequest.current?.abort()
  }, [])

  async function readFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file || disabled || fileRequest.current) return
    const controller = new AbortController()
    fileRequest.current = controller
    setFileState({ busy: true, error: "", notice: "" })
    try {
      const body = new FormData()
      body.append("file", file)
      const result = await apiFetch("/trade/source-text", { token, method: "POST", body, signal: controller.signal })
      if (controller.signal.aborted) return
      const combined = sourceText.trim() ? `${sourceText}\n\n${result.text}` : result.text
      if (combined.length > 20000) {
        setFileState({ busy: false, error: "첨부 내용을 더하면 원문 입력 한도 20,000자를 넘습니다. 기존 원문을 줄이거나 파일을 나누어 주세요.", notice: "" })
        return
      }
      ;(onTextChange ?? setText)(combined)
      setFileState({ busy: false, error: "", notice: `${file.name}에서 텍스트를 가져왔습니다.${result.review_required ? " 판독이 불확실한 부분은 원문과 대조해 주세요." : " 내용을 확인한 뒤 원문에서 정보를 가져오세요."}` })
    } catch (error) {
      if (!controller.signal.aborted) setFileState({ busy: false, error: error.message, notice: "" })
    } finally {
      if (fileRequest.current === controller) fileRequest.current = null
    }
  }

  async function manageKey(event, method) {
    event.preventDefault()
    if (keyRequest.current) return
    const controller = new AbortController()
    const form = event.currentTarget
    keyRequest.current = controller
    setKeyState({ busy: true, error: "", notice: "" })
    try {
      await apiFetch("/openai-key", { token, method, signal: controller.signal,
        ...(method === "PUT" ? { body: new FormData(form) } : {}) })
      if (controller.signal.aborted) return
      form.reset()
      setKeyState({ busy: false, error: "", notice: method === "PUT" ? `개인 키를 저장했습니다. 원문으로 ${kind} 만들기를 눌러 주세요.` : "개인 키를 삭제했습니다." })
    } catch (error) {
      if (!controller.signal.aborted) setKeyState({ busy: false, error: error.message, notice: "" })
    } finally {
      if (keyRequest.current === controller) keyRequest.current = null
    }
  }

  return <section className="ai-input" aria-label={`${kind} 문장 추출`}>
    <h2 tabIndex={-1} ref={headingRef}>거래 원문을 붙여넣어 주세요</h2>
    <p className="pi-question-note">거래 정보를 가져온 뒤, 빠진 내용만 물어볼게요.</p>
    <form onSubmit={(event) => { event.preventDefault(); if (!disabled && !extractDisabled && !fileState.busy && sourceText.trim()) onExtract(sourceText) }}>
      <div className="field"><label htmlFor={textId}>거래 원문</label><textarea id={textId} value={sourceText} maxLength={20000} rows={4} disabled={disabled || fileState.busy}
        onChange={(event) => (onTextChange ?? setText)(event.target.value)} placeholder="품목·수량·거래처·납품·지급 조건을 입력하세요." /></div>
      <p className="section-note">원문은 OpenAI로 분석하며 새 {kind} 초안으로 저장해요. 첨부 파일은 텍스트로 불러온 뒤 내용을 확인할 수 있어요.</p>
      <div className="source-upload">
        <label className={`btn source-file-button ${disabled || fileState.busy ? "is-disabled" : ""}`} htmlFor={fileId}>{fileState.busy ? "파일을 읽는 중…" : "파일 첨부"}
          <input id={fileId} className="source-file-input" type="file" accept=".pdf,.xlsx,.txt,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/plain,image/png,image/jpeg"
            onChange={readFile} disabled={disabled || fileState.busy} />
        </label>
        <span className="section-note">PDF·Excel(XLSX)·TXT·PNG·JPG · 파일당 20MiB · 문서는 최대 5페이지</span>
      </div>
      {fileState.error && <p className="form-error" role="alert">{fileState.error}</p>}
      {fileState.notice && <p className="form-success" role="status">{fileState.notice}</p>}
      <button className="btn blue" type="submit" disabled={disabled || extractDisabled || fileState.busy || !sourceText.trim()}>{disabled || fileState.busy ? "정보를 가져오는 중…" : "원문에서 정보 가져오기"}</button>
    </form>
    <details className="ai-key"><summary>개인 OpenAI 키 등록·교체</summary>
      <p className="section-note">서버 저장 방식에서는 본인 키를 암호화해 보관합니다. 개인 PC 실행 방식은 PC의 환경 파일을 사용합니다. 수동 {kind} 작성은 AI 키 없이 가능합니다.</p>
      <form onSubmit={(event) => manageKey(event, "PUT")}>
        <div className="field"><label htmlFor={keyId}>개인 OpenAI API 키</label><input id={keyId} name="api_key" type="password" maxLength={512} autoComplete="off" required disabled={disabled || keyState.busy} /></div>
        <div className="form-actions"><button className="btn" type="submit" disabled={disabled || keyState.busy}>키 등록·교체</button></div>
      </form>
      <form onSubmit={(event) => manageKey(event, "DELETE")}><button className="btn" type="submit" disabled={disabled || keyState.busy}>저장된 키 삭제</button></form>
      {keyState.error && <p className="form-error" role="alert">{keyState.error}</p>}
      {keyState.notice && <p className="form-success" role="status">{keyState.notice}</p>}
    </details>
  </section>
}
