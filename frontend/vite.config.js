import react from "@vitejs/plugin-react"
import { fileURLToPath } from "node:url"
import { defineConfig, loadEnv } from "vite"

// 개발 포트는 루트 .env의 FRONTEND_PORT를 사용하고 비우면 5174다.
// /api 요청은 로컬 FastAPI(http://127.0.0.1:8000)로 보낸다.
// 운영: base /app 아래 빌드해 기존 FastAPI가 같은 출처로 제공한다(계획 21절).
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
    envPrefix: ["SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"],
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
