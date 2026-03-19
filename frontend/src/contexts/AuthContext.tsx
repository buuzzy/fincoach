import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

const SESSION_KEY = 'tm_logged_in'

interface AuthContextValue {
  isAuthenticated: boolean
  setLoggedIn: () => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(
    () => sessionStorage.getItem(SESSION_KEY) === '1',
  )

  const setLoggedIn = useCallback(() => {
    sessionStorage.setItem(SESSION_KEY, '1')
    setIsAuthenticated(true)
  }, [])

  const logout = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setIsAuthenticated(false)
  }, [])

  return (
    <AuthContext.Provider value={{ isAuthenticated, setLoggedIn, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
