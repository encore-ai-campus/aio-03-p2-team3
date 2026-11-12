import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// 개발: Vite(http://localhost:5173)의 /api 요청을 로컬 FastAPI(http://127.0.0.1:8000)로 보낸다.
// 운영: base /app 아래 빌드해 기존 FastAPI가 같은 출처로 제공한다(계획 21절).
export default defineConfig({
  base: "/app/",
  envDir: "..",
  // 루트 .env를 공유하되 공개 URL·publishable 키만 브라우저에 전달한다.
  envPrefix: ["SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"],
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
})
