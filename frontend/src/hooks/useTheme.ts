import { useCallback, useState } from 'react'

/** Light/dark theme. The initial class is set by an inline script in index.html (no flash on load). */
export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev
      document.documentElement.classList.toggle('dark', next)
      try {
        localStorage.setItem('theme', next ? 'dark' : 'light')
      } catch {
        /* storage can be blocked (private mode); the theme just won't persist */
      }
      return next
    })
  }, [])

  return { dark, toggle }
}
