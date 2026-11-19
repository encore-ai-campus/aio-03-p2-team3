// FastAPI JSON API 공통 fetch(CONTRACT 9.1절 Bearer 전용 경로).
// - Bearer 헤더: 호출 쪽에서 받은 Supabase access token을 붙인다.
// - 오류 정규화: 서버 오류 본문 {"error": {"code", "message"}}를 ApiError(status, code, message)로 바꾼다.
// - 401 처리: 401도 ApiError로 던지고 AuthContext이 로컬 세션을 정리한 뒤 로그인 복구 안내로 이어진다.

// SPA가 실제 서비스되는 기본 경로(Vite base와 함께 정해진다). 같은 출처 /app 배포는 "/app", 루트 정적 사이트는 "".
// 라우터 basename은 빈 값을 받지 않으므로 쓰는 쪽에서 || "/"로 보정한다.
// Vite 밖(node --test)에서는 import.meta.env가 없으므로 선택 접근으로 기본값을 쓴다.
const env = import.meta.env ?? {}
export const APP_BASE = (env.BASE_URL || "/").replace(/\/+$/, "")

// 분리 배포에서는 VITE_API_BASE_URL(서버 주소)로 /api를 보내고,
// 같은 출처 실행(로컬 vite 프록시·서버 /app 제공)에서는 비워 상대 경로를 쓴다.
const API_BASE = (env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "")

// 서버가 알려준 /app 접두 화면 주소를 실제 서비스 경로로 바꾼다. 접두가 없으면 그대로 둔다.
export const appHref = (url) => {
  if (!url.startsWith("/app")) return url
  return APP_BASE + (url.slice(4) || "/")
}

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

export async function apiFetch(path, { method = "GET", token, body, signal, responseType = "json" } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const isForm = body instanceof FormData
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json"
  let response
  try {
    response = await fetch(`${API_BASE}/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error.name === "AbortError") throw error
    throw new ApiError(0, "network", "서버에 연결하지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해 주세요.")
  }
  if (response.ok && responseType === "response") return response
  if (response.ok && responseType === "blob") return response.blob()
  const data = await response.json().catch((error) => {
    if (error.name === "AbortError") throw error
    return null
  })
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error?.code ?? String(response.status),
      data?.error?.message ?? (Array.isArray(data?.detail)
        ? data.detail.map((issue) => issue.msg.replace(/^Value error, /, "")).join(" / ")
        : typeof data?.detail === "string" ? data.detail : `요청이 실패했습니다(${response.status}).`),
    )
  }
  return data
}

export async function downloadFile(file, token, signal) {
  if (!file.download_url.startsWith("/api/")) throw new ApiError(0, "invalid_file", "파일 주소를 확인할 수 없습니다.")
  const blob = await apiFetch(file.download_url.slice(4), { token, signal, responseType: "blob" })
  if (signal?.aborted) return
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = file.filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

// GET /api/me — 인증 상태·내부 user_id·프로필·Gmail 연결 상태(로그인·새로고침 복구의 시작점).
export function fetchMe(token, signal) {
  return apiFetch("/me", { token, signal })
}
