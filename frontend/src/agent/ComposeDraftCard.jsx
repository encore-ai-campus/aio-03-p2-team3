import { useEffect, useState } from "react"
import { apiFetch } from "../api"

export default function ComposeDraftCard({ draftId, token }) {
  const [draft, setDraft] = useState(null)
  const [recipients, setRecipients] = useState("")
  const [reload, setReload] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)
  const path = `/mail/compose-drafts/${encodeURIComponent(draftId)}`

  useEffect(() => {
    const controller = new AbortController()
    apiFetch(path, { token, signal: controller.signal }).then(value => {
      setDraft(value)
      setRecipients(value.recipients.join(", "))
      setError("")
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure.message)
    })
    return () => controller.abort()
  }, [path, reload, token])

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    setError("")
    setSaved(false)
    try {
      const updated = await apiFetch(path, { method: "PUT", token, body: {
        revision: draft.revision, subject: draft.subject, body: draft.body,
        recipients: recipients.split(/[,\n]+/).map(value => value.trim()).filter(Boolean),
      } })
      setDraft(updated)
      setRecipients(updated.recipients.join(", "))
      setSaved(true)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setSaving(false)
    }
  }

  return <section className="compose-draft-result" aria-label="새 메일 초안">
    {error && <div role="alert">{error} <button type="button" className="btn"
      onClick={() => setReload(value => value + 1)}>최신 초안 읽기</button></div>}
    {draft ? <form onSubmit={save}>
      <label className="q-field">받는 사람<input value={recipients} required disabled={saving}
        onChange={event => { setRecipients(event.target.value); setSaved(false) }} /></label>
      <label className="q-field">제목<input value={draft.subject} required maxLength={200} disabled={saving}
        onChange={event => { setDraft({ ...draft, subject: event.target.value }); setSaved(false) }} /></label>
      <label className="q-field">본문<textarea value={draft.body} required maxLength={25000} rows={7} disabled={saving}
        onChange={event => { setDraft({ ...draft, body: event.target.value }); setSaved(false) }} /></label>
      <footer className="compose-draft-actions">
        <span role="status">{saved ? "초안 수정 내용을 저장했습니다." : "앱에 저장된 새 메일 초안"}</span>
        <button type="submit" className="btn blue" disabled={saving}>{saving ? "저장 중…" : "초안 저장"}</button>
      </footer>
    </form> : !error && <p role="status">초안을 읽고 있습니다…</p>}
  </section>
}
