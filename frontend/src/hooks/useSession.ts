import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import type { Role, SessionInfo } from '../types'

/** Who is signed in. The server owns the truth (a signed cookie); this just mirrors it for the UI. */
export function useSession() {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .me()
      .then(setSession)
      .catch((e: unknown) => {
        // 401 just means "not signed in yet": show the landing page, not an error.
        if (!(e instanceof ApiError && e.status === 401)) setError((e as Error).message)
      })
      .finally(() => setLoading(false))
  }, [])

  const run = useCallback(async (action: () => Promise<SessionInfo | { ok: boolean }>) => {
    setError(null)
    try {
      return await action()
    } catch (e) {
      setError((e as Error).message)
      return null
    }
  }, [])

  const login = useCallback(
    async (persona: Role, memberId?: string) => {
      const next = (await run(() => api.login(persona, memberId))) as SessionInfo | null
      if (next) setSession(next)
    },
    [run],
  )

  const logout = useCallback(async () => {
    await run(() => api.logout())
    setSession(null)
  }, [run])

  const selectPatient = useCallback(
    async (memberId: string | null) => {
      const next = (await run(() => api.selectPatient(memberId))) as SessionInfo | null
      if (next) setSession(next)
    },
    [run],
  )

  const expire = useCallback(() => setSession(null), [])

  return { session, loading, error, login, logout, selectPatient, expire, clearError: () => setError(null) }
}
