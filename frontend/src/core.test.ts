import { describe, expect, it } from 'vitest'
import { applyEvent, newBotMessage } from './chatState'
import { SSEParser } from './sse'
import type { FinalEvent, StreamEvent } from './types'

const sse = (event: string, payload: object) => `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`

describe('SSEParser', () => {
  it('parses complete events and ignores comment lines', () => {
    const p = new SSEParser()
    const out = p.feed(': connected\n\n' + sse('meta', { type: 'meta', conversation_id: 'abc' }))
    expect(out).toEqual([{ type: 'meta', conversation_id: 'abc' }])
  })

  it('handles an event split across network chunks', () => {
    const p = new SSEParser()
    const whole = sse('status', { type: 'status', stage: 'gate', message: 'Understanding…' })
    const cut = 23 // mid-way through the JSON
    expect(p.feed(whole.slice(0, cut))).toEqual([])
    expect(p.feed(whole.slice(cut))).toEqual([{ type: 'status', stage: 'gate', message: 'Understanding…' }])
  })

  it('handles several events in one chunk and CRLF line endings', () => {
    const p = new SSEParser()
    const chunk = (sse('status', { type: 'status', stage: 'guard', message: 'a' }) +
      sse('done', { type: 'done' })).replace(/\n/g, '\r\n')
    expect(p.feed(chunk).map((e) => e.type)).toEqual(['status', 'done'])
  })

  it('keeps unicode intact and survives malformed events', () => {
    const p = new SSEParser()
    const out = p.feed('event: x\ndata: {not json}\n\n' + sse('error', { type: 'error', message: 'café — ✓' }))
    expect(out).toEqual([{ type: 'error', message: 'café — ✓' }])
  })
})

const run = (events: StreamEvent[]) => events.reduce((m, e) => applyEvent(m, e, 1000), newBotMessage('b', 0))

const final: FinalEvent = { type: 'final', text: 'ok', kind: 'answer', citations: [], sources: [], tools: [] }

describe('applyEvent', () => {
  it('walks the stages in order and completes everything on final', () => {
    const m = run([
      { type: 'status', stage: 'guard', message: '' },
      { type: 'status', stage: 'gate', message: '' },
      { type: 'status', stage: 'compose', message: '' },
      { type: 'status', stage: 'verify', message: '' },
      final,
    ])
    expect(m.stages.map((s) => s.id)).toEqual(['guard', 'gate', 'compose', 'verify'])
    expect(m.stages.every((s) => s.state === 'done')).toBe(true)
    expect(m.status).toBe('done')
    expect(m.endedAt).toBe(1000)
  })

  it('treats tools and retrieval as PARALLEL stages with independent completion', () => {
    const m = run([
      { type: 'status', stage: 'gate', message: '' },
      { type: 'status', stage: 'tools', message: '' },
      { type: 'status', stage: 'retrieve', message: '' },
      { type: 'tool', name: 'get_drug_coverage', status: 'running' },
    ])
    const state = (id: string) => m.stages.find((s) => s.id === id)?.state
    expect(state('tools')).toBe('active') // NOT finished just because 'retrieve' started
    expect(state('retrieve')).toBe('active')

    const m2 = applyEvent(m, { type: 'retrieval', count: 5, sources: [] })
    expect(m2.stages.find((s) => s.id === 'retrieve')?.state).toBe('done')
    expect(m2.stages.find((s) => s.id === 'tools')?.state).toBe('active') // tool still running

    const m3 = applyEvent(m2, { type: 'tool', name: 'get_drug_coverage', status: 'ok' })
    expect(m3.tools).toEqual([{ name: 'get_drug_coverage', status: 'ok', error: undefined }])
    expect(m3.stages.find((s) => s.id === 'tools')?.state).toBe('done')
  })

  it('keeps a tool error visible', () => {
    const m = run([
      { type: 'tool', name: 'list_prescriptions', status: 'running' },
      { type: 'tool', name: 'list_prescriptions', status: 'error', error: 'No patient is selected.' },
    ])
    expect(m.tools[0]).toMatchObject({ status: 'error', error: 'No patient is selected.' })
  })

  it('does not duplicate a repeated stage and ignores meta/done', () => {
    const m = run([
      { type: 'meta', conversation_id: 'c' },
      { type: 'status', stage: 'guard', message: '' },
      { type: 'status', stage: 'guard', message: '' },
      { type: 'done' },
    ])
    expect(m.stages).toHaveLength(1)
  })

  it('records an error event on the message', () => {
    expect(run([{ type: 'error', message: 'boom' }]).error).toBe('boom')
  })
})
