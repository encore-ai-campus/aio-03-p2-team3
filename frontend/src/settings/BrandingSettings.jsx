import { useState } from "react"
import PrivateImage from "../components/PrivateImage"
import SettingsForm, { Field } from "./SettingsForm"

function BrandingCard({ kind, label, fileId, token, save, saving, error, notice, activeKind, setActiveKind, clearStatus }) {
  const [fileError, setFileError] = useState("")
  return (
    <section className="branding-card" aria-label={`${label} 설정`}>
      <h3 className="section-title">{label}</h3>
      <PrivateImage path={fileId ? `/files/${fileId}/download` : null} token={token} label={label} />
      <SettingsForm saving={saving} error={fileError || (activeKind === kind ? error : "")}
        notice={activeKind === kind ? notice : ""} onSubmit={({ image }) => {
          setActiveKind(kind)
          if (image.size === 0 || image.size > 2 * 1024 * 1024 || !image.name.toLowerCase().endsWith(".png")) {
            setFileError("비어 있지 않은 2MiB 이하 PNG 파일을 선택하세요.")
            return
          }
          setFileError("")
          const form = new FormData()
          form.set("image", image)
          save(`/branding/${kind}`, form, "POST")
        }}>
        <Field label={`${label} PNG 파일`} name="image" type="file" accept="image/png,.png" required onChange={() => {
          setFileError("")
          setActiveKind(null)
          clearStatus()
        }} />
      </SettingsForm>
    </section>
  )
}

export default function BrandingSettings({ data, token, ...props }) {
  const [activeKind, setActiveKind] = useState(null)
  return (
    <>
      <p className="section-note">RGB/RGBA PNG, 파일당 2MiB 이하. 저장한 이미지는 새 검토부터 적용되며 기존 발급 파일은 유지됩니다.</p>
      <div className="branding-grid">
        {[{ kind: "logo", label: "로고" }, { kind: "seal", label: "직인" }].map(({ kind, label }) => (
          <BrandingCard key={kind} kind={kind} label={label} fileId={data.branding[`${kind}_file_id`]}
            token={token} {...props} activeKind={activeKind} setActiveKind={setActiveKind} />
        ))}
      </div>
    </>
  )
}
