import { useEffect, useState } from "react"
import { apiFetch } from "../api"
import SettingsForm, { Field } from "./SettingsForm"

function ImagePreview({ fileId, token, label }) {
  const [preview, setPreview] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!fileId) return undefined
    const controller = new AbortController()
    let objectUrl
    apiFetch(`/files/${fileId}/download`, { token, signal: controller.signal, responseType: "blob" })
      .then((blob) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setPreview({ fileId, url: objectUrl })
      }).catch((error) => {
        if (!controller.signal.aborted) setPreview({ fileId, error: error.message })
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId, token, retry])

  if (!fileId) return <div className="image-preview"><span>등록한 {label}이 없습니다.</span></div>
  if (preview?.fileId !== fileId) return <div className="image-preview" role="status">이미지를 불러오는 중…</div>
  if (preview.error) return <div className="image-preview"><p role="alert">{preview.error}</p><button type="button" className="btn" onClick={() => setRetry((value) => value + 1)}>다시 읽기</button></div>
  return <div className="image-preview"><img src={preview.url} alt={`저장된 회사 ${label}`} /></div>
}

function BrandingCard({ kind, label, fileId, token, save, saving, error, notice, activeKind, setActiveKind, clearStatus }) {
  const [fileError, setFileError] = useState("")
  return (
    <section className="branding-card" aria-label={`${label} 설정`}>
      <h3 className="section-title">{label}</h3>
      <ImagePreview fileId={fileId} token={token} label={label} />
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
