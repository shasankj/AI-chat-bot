import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, streamChat } from './api'

afterEach(() => vi.unstubAllGlobals())
const stubFetch = (impl: () => Promise<Response>) => vi.stubGlobal('fetch', vi.fn(impl))
const failureOf = async (p: Promise<unknown>) => { try { await p } catch (e) { return e as ApiError } throw new Error('expected a failure') }

describe('API error messages', () => {
  it('explains a dead backend when the dev proxy answers 502 with plain text', async () => {
    stubFetch(async () => new Response('Bad Gateway', { status: 502, headers: { 'content-type': 'text/plain' } }))
    const err = await failureOf(api.personas())
    expect(err.status).toBe(502)
    expect(err.message).toMatch(/backend is probably not running/i)
    expect(err.message).toMatch(/uvicorn/)
  })

  it('treats a 503 WITHOUT our JSON shape as a dead backend too', async () => {
    stubFetch(async () => new Response('Service Unavailable', { status: 503 }))
    expect((await failureOf(api.me())).message).toMatch(/not running/i)
  })

  it("keeps the server's own message for a genuine 503 (assistant busy) and reads Retry-After", async () => {
    stubFetch(async () => new Response(JSON.stringify({ error: 'The assistant is busy. Please retry in a few seconds.' }),
      { status: 503, headers: { 'content-type': 'application/json', 'retry-after': '5' } }))
    const err = await failureOf(api.me())
    expect(err.message).toBe('The assistant is busy. Please retry in a few seconds.')
    expect(err.retryAfter).toBe(5)
  })

  it('reports a network failure (connection refused) clearly', async () => {
    stubFetch(async () => { throw new TypeError('fetch failed') })
    expect((await failureOf(api.me())).message).toMatch(/not running/i)
  })

  it('shows validation details without crashing', async () => {
    stubFetch(async () => new Response(JSON.stringify({ error: 'Invalid request.', details: ['question: too long'] }), { status: 422 }))
    expect((await failureOf(api.login('guest'))).message).toBe('Invalid request. question: too long')
  })

  it('streamChat surfaces a 429 with its retry hint and a dead backend', async () => {
    stubFetch(async () => new Response(JSON.stringify({ error: 'Too many requests. Try again in 12s.' }),
      { status: 429, headers: { 'retry-after': '12' } }))
    const err = await failureOf(streamChat('hi', null, new AbortController().signal, () => {}))
    expect(err.status).toBe(429)
    expect(err.message).toContain('12s')

    stubFetch(async () => new Response('Bad Gateway', { status: 502 }))
    expect((await failureOf(streamChat('hi', null, new AbortController().signal, () => {}))).message).toMatch(/not running/i)
  })
})
