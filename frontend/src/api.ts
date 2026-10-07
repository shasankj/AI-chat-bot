import { SSEParser } from './sse'
import type {
  AdminSummary,
  PatientSummary,
  Persona,
  PolicySource,
  Role,
  SessionInfo,
  StreamEvent,
} from './types'

const BASE = '/api' // proxied to FastAPI by vite.config.ts

export class ApiError extends Error {
  status: number
  retryAfter: number | null
  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.retryAfter = retryAfter
  }
}

const BACKEND_DOWN =
  'Cannot reach the Care Bot API. The backend is probably not running. Start it with: ' +
  'cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000  (or run ./dev.sh from the project root).'

/** Turn any failed response into an ApiError carrying the SERVER's message (we show errors, not hide them). */
async function failure(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`
  let fromApi = false // did the message come from OUR server (JSON {"error": ...})?
  try {
    const body = await res.json()
    if (body?.error) { message = body.error; fromApi = true }
    if (Array.isArray(body?.details) && body.details.length) message += ` ${body.details.join('; ')}`
  } catch {
    /* body was not JSON */
  }
  // The dev proxy answers 502/503/504 (with a plain-text body) when FastAPI isn't running. Our own API
  // always replies with JSON, so a gateway status WITHOUT that shape means "the backend is down".
  if (!fromApi && [502, 503, 504].includes(res.status)) message = BACKEND_DOWN
  const retry = Number(res.headers.get('retry-after'))
  return new ApiError(res.status, message, Number.isFinite(retry) && retry > 0 ? retry : null)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      credentials: 'include', // send/receive the HttpOnly session cookie
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError(0, BACKEND_DOWN)
  }
  if (!res.ok) throw await failure(res)
  return (await res.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  personas: () => request<{ demo_notice: string; personas: Persona[] }>('/auth/personas'),
  sources: () => request<{ sources: PolicySource[] }>('/sources'),
  me: () => request<SessionInfo>('/me'),
  login: (persona: Role, member_id?: string) =>
    post<SessionInfo>('/auth/demo-login', member_id ? { persona, member_id } : { persona }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  patients: () => request<{ patients: PatientSummary[] }>('/patients'),
  selectPatient: (member_id: string | null) => post<SessionInfo>('/session/select-patient', { member_id }),
  adminSummary: () => request<AdminSummary>('/admin/summary'),
}

/**
 * Chat over Server-Sent Events.
 *
 * We use fetch() + a stream reader instead of the browser's EventSource because EventSource can only
 * send GET requests with no body, and chat is a POST. Aborting the AbortSignal closes the connection,
 * which the server notices (and stops the turn).
 */
export async function streamChat(
  question: string,
  conversationId: string | null,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(BASE + '/chat', {
      method: 'POST',
      credentials: 'include',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(conversationId ? { question, conversation_id: conversationId } : { question }),
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, BACKEND_DOWN)
  }
  if (!res.ok) throw await failure(res)
  if (!res.body) throw new ApiError(0, 'The browser did not provide a response stream.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SSEParser()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (const event of parser.feed(decoder.decode(value, { stream: true }))) onEvent(event)
  }
}
