import { useState } from "react"

/** Candidate editing is persisted before the existing approval flow can send anything. */
export default function ReplyCandidateEditor({ candidate, token, busy, onSaved, onError }) {
  const [editing, setEditing] = useState(false)
  const [subject, setSubject] = useState(candidate.subject)
  const [body, setBody] = useState(candidate.body)
  const [saving, setSaving] = useState(false)
  const editable = ["pending", "send_failed"].includes(candidate.status)

  async function save() {
    if (!subject.trim() || !body.trim()) { onError("제목과 본문을 모두 입력해 주세요."); return }
    if (subject.length > 500 || body.length > 50000) { onError("제목 또는 본문이 너무 깁니다."); return }
    setSaving(true)
    try {
      // Use the same bearer client as the mailbox page; never send a message from the editor.
      const { apiFetch } = await import("../api")
      await apiFetch(`/mail/candidates/${candidate.id}`, {
        token, method: "PUT", body: {
          subject, body, expected_subject: candidate.subject, expected_body: candidate.body,
        },
      })
      setEditing(false)
      onSaved()
    } catch (error) { onError(error.message) }
    finally { setSaving(false) }
  }

  if (!editing) return <>
    <p className="cand-body">{candidate.body}</p>
    {editable && <button type="button" className="btn sm" disabled={busy}
      onClick={() => { setSubject(candidate.subject); setBody(candidate.body); setEditing(true) }}>
      제목·본문 수정하기
    </button>}
  </>
  return <div className="reply-edit">
    <label htmlFor={`reply-subject-${candidate.id}`}>메일 제목</label>
    <input id={`reply-subject-${candidate.id}`} value={subject}
      maxLength={500} onChange={(event) => setSubject(event.target.value)} disabled={saving} />
    <label htmlFor={`reply-body-${candidate.id}`}>메일 본문</label>
    <textarea id={`reply-body-${candidate.id}`} rows={8} value={body}
      maxLength={50000} onChange={(event) => setBody(event.target.value)} disabled={saving} />
    <div className="reply-edit-actions">
      <button type="button" className="btn blue" disabled={saving || busy || !subject.trim() || !body.trim()} onClick={save}>
        {saving ? "저장 중…" : "수정 내용 저장"}
      </button>
      <button type="button" className="btn" disabled={saving} onClick={() => setEditing(false)}>취소</button>
    </div>
  </div>
}
