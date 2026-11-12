import { createClient } from "@supabase/supabase-js"

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// Auth 클라이언트는 이 파일 한 곳에 한 개만 둔다(계획 6절).
// 설정이 없으면 null을 내보내고 로그인 화면이 '설정 누락' 안내를 보인다.
export const supabase = supabaseUrl && supabasePublishableKey
  ? createClient(supabaseUrl, supabasePublishableKey, { auth: { flowType: "pkce" } })
  : null
