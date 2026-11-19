import react from "@vitejs/plugin-react"
import { fileURLToPath } from "node:url"
import { defineConfig, loadEnv } from "vite"

// 개발 포트는 루트 .env의 FRONTEND_PORT를 사용하고 비우면 5174다.
// /api 요청은 로컬 FastAPI(http://127.0.0.1:8000)로 보낸다.
// 운영(같은 출처): base /app 아래 빌드해 기존 FastAPI가 같은 출처로 제공한다(계획 21절).
// 운영(분리 배포): 정적 사이트 빌드에서 --base=/를 붙여 루트 경로로 서비스하고 /api는 VITE_API_BASE_URL의 서버로 보낸다.
export default defineConfig(({ mode }) => {
  const envDir = fileURLToPath(new URL("..", import.meta.url))
  const env = loadEnv(mode, envDir, "FRONTEND_PORT")
  const port = Number(env.FRONTEND_PORT?.trim() || 5174)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("FRONTEND_PORT는 1~65535 사이의 정수로 설정해 주세요.")
  }
  return {
    base: "/app/",
    envDir,
    // 루트 .env를 공유하되 공개 URL·publishable 키만 브라우저에 전달한다.
    // VITE_API_BASE_URL은 분리 배포에서만 채우고 같은 출처 실행에서는 비워 상대 /api를 쓴다.
    envPrefix: ["SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "VITE_API_BASE_URL"],
    plugins: [react()],
    server: {
      port,
      strictPort: true,
      proxy: {
        "/api": "http://127.0.0.1:8000",
      },
    },
  }
})
