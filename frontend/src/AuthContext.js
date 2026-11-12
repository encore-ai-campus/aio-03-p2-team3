import { createContext } from "react"

// 컨텍스트 객체만 둔다(Provider 컴포넌트는 AuthProvider.jsx, 훅은 useAuth.js).
export const AuthContext = createContext(null)
