# Care Bot frontend

React 19 + TypeScript + Vite + Tailwind CSS. See the [project README](../README.md) for what it is, how to run everything
(`./dev.sh` from the project root) and how to test it.

```bash
npm install
npm run dev        # http://localhost:5173  (proxies /api/* to the backend on :8000)
npm test           # Vitest: SSE parser, state reducer, API error messages
npx tsc -b && npx oxlint && npm run build
```

Key files: `src/api.ts` (typed client + SSE streaming), `src/sse.ts` (incremental parser), `src/chatState.ts`
(pure reducer from stream events to message state), `src/hooks/`, `src/components/`.
