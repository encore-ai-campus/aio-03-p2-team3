import { useEffect, useId, useRef, useState } from "react"
import { apiFetch } from "../api"

export default function AIInput({ token, disabled, onExtract }) {
  const [text, setText] = useState("")
  const [keyState, setKeyState] = useState({ busy: false, error: "", notice: "" })
  const keyRequest = useRef(null)
  const textId = useId()
  const keyId = useId()
  useEffect(() => () => keyRequest.current?.abort(), [])

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
      setKeyState({ busy: false, error: "", notice: method === "PUT" ? "개인 키를 저장했습니다. 원문으로 PI 만들기를 눌러 주세요." : "개인 키를 삭제했습니다." })
    } catch (error) {
      if (!controller.signal.aborted) setKeyState({ busy: false, error: error.message, notice: "" })
    } finally {
      if (keyRequest.current === controller) keyRequest.current = null
    }
  }

  return <section className="card ai-input" aria-label="PI 문장 추출">
    <h2 className="section-title">문장으로 PI 초안 만들기</h2>
    <p className="section-note">거래 조건을 입력하면 OpenAI가 정보를 추출합니다. 금액과 발급 가능 여부는 서버가 검증하며 메일을 보내지 않습니다.</p>
    <form onSubmit={(event) => { event.preventDefault(); if (!disabled && text.trim()) onExtract(text) }}>
      <div className="field"><label htmlFor={textId}>거래 원문</label><textarea id={textId} value={text} maxLength={20000} rows={4} disabled={disabled}
        onChange={(event) => setText(event.target.value)} placeholder="품목·수량·거래처·납품·지급 조건을 입력하세요." /></div>
      <p className="section-note">새 PI로 저장하며 현재 입력을 교체합니다. 수정 중인 값은 먼저 저장하세요. 첨부 파일 자동 추출은 포함하지 않습니다.</p>
      <button className="btn blue" type="submit" disabled={disabled || !text.trim()}>원문으로 새 PI 만들기</button>
    </form>
    <details className="ai-key"><summary>개인 OpenAI 키 등록·교체</summary>
      <p className="section-note">서버 저장 방식에서는 본인 키를 암호화해 보관합니다. 개인 PC 실행 방식은 PC의 환경 파일을 사용합니다. 수동 PI 작성은 AI 키 없이 가능합니다.</p>
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
