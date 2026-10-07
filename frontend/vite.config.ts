import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // The browser only ever talks to http://localhost:5173. Requests to /api/* are forwarded to
    // FastAPI on :8000. One origin means no CORS preflights and the session cookie "just works".
    // (The Origin header stays http://localhost:5173, which the backend allows.)
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: { environment: 'node' },
})
