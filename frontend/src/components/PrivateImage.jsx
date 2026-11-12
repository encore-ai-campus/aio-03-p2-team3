import { useEffect, useState } from "react"
import { apiFetch } from "../api"

export default function PrivateImage({ path, token, label }) {
  const [preview, setPreview] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!path) return undefined
    const controller = new AbortController()
    let objectUrl
    apiFetch(path, { token, signal: controller.signal, responseType: "blob" })
      .then((blob) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setPreview({ path, url: objectUrl })
      }).catch((error) => {
        if (!controller.signal.aborted) setPreview({ path, error: error.message })
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path, token, retry])

  if (!path) return <div className="image-preview"><span>등록한 {label}이 없습니다.</span></div>
  if (preview?.path !== path) return <div className="image-preview" role="status">이미지를 불러오는 중…</div>
  if (preview.error) return <div className="image-preview"><p role="alert">{preview.error}</p><button type="button" className="btn" onClick={() => setRetry((value) => value + 1)}>다시 읽기</button></div>
  return <div className="image-preview"><img src={preview.url} alt={`저장된 회사 ${label}`} /></div>
}

