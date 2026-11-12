import { useId } from "react"

export function Field({ label, name, value, multiline = false, ...props }) {
  const id = useId()
  const Control = multiline ? "textarea" : "input"
  return (
    <div className={`field${multiline ? " full" : ""}`}>
      <label htmlFor={id}>{label}</label>
      <Control id={id} name={name} defaultValue={value ?? ""} maxLength={4000} {...props} />
    </div>
  )
}

export default function SettingsForm({ children, onSubmit, saving, error, notice, id }) {
  return (
    <form id={id} onSubmit={(event) => {
      event.preventDefault()
      if (!saving) onSubmit(Object.fromEntries(new FormData(event.currentTarget)))
    }}>
      <fieldset disabled={saving} className="settings-form">
        <div className="settings-fields">{children}</div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="form-success" role="status">{notice}</p>}
        <div className="form-actions">
          <button className="btn" type="reset">입력 되돌리기</button>
          <button className="btn blue" type="submit">{saving ? "저장 중…" : "변경 저장"}</button>
        </div>
      </fieldset>
    </form>
  )
}
