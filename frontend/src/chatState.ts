import type { FinalEvent, RetrievalInfo, StreamEvent, ToolRun } from './types'

export interface Stage {
  id: string
  label: string
  state: 'active' | 'done'
}

export interface UserMessage {
  id: string
  role: 'user'
  text: string
}

export interface BotMessage {
  id: string
  role: 'assistant'
  status: 'streaming' | 'done' | 'aborted' | 'failed'
  startedAt: number
  endedAt?: number
  stages: Stage[]
  tools: ToolRun[]
  retrieval?: RetrievalInfo
  final?: FinalEvent
  error?: string
}

export type ChatMessage = UserMessage | BotMessage

const STAGE_LABELS: Record<string, string> = {
  guard: 'Safety check',
  gate: 'Understanding the question',
  tools: 'Looking up records (MCP)',
  retrieve: 'Searching policy documents',
  screen: 'Screening retrieved text',
  compose: 'Drafting the answer',
  verify: 'Verifying against the sources',
}

export const newBotMessage = (id: string, now = Date.now()): BotMessage => ({
  id, role: 'assistant', status: 'streaming', startedAt: now, stages: [], tools: [],
})

const markDone = (stages: Stage[], ids: string[]): Stage[] =>
  stages.map((s) => (ids.includes(s.id) ? { ...s, state: 'done' as const } : s))

/**
 * Pure reducer: (message so far, one stream event) -> new message. Pure functions are trivial to test
 * and keep React rendering predictable.
 *
 * Subtlety: "tools" and "retrieve" run IN PARALLEL on the server, so we can't simply finish the
 * previous stage when the next one starts. Each stage has its own completion signal instead.
 */
export function applyEvent(msg: BotMessage, ev: StreamEvent, now = Date.now()): BotMessage {
  switch (ev.type) {
    case 'status': {
      if (msg.stages.some((s) => s.id === ev.stage)) return msg
      let stages = msg.stages
      if (ev.stage === 'gate') stages = markDone(stages, ['guard'])
      if (ev.stage === 'compose') stages = markDone(stages, ['guard', 'gate', 'tools', 'retrieve', 'screen'])
      if (ev.stage === 'verify') stages = markDone(stages, ['compose'])
      return { ...msg, stages: [...stages, { id: ev.stage, label: STAGE_LABELS[ev.stage] ?? ev.message, state: 'active' }] }
    }
    case 'retrieval':
      return { ...msg, retrieval: { count: ev.count, sources: ev.sources }, stages: markDone(msg.stages, ['retrieve']) }
    case 'tool': {
      let tools = msg.tools
      if (ev.status === 'running') {
        tools = [...tools, { name: ev.name, status: 'running' }]
      } else {
        const i = tools.findIndex((t) => t.name === ev.name && t.status === 'running')
        const updated: ToolRun = { name: ev.name, status: ev.status, error: ev.error }
        tools = i >= 0 ? tools.map((t, j) => (j === i ? updated : t)) : [...tools, updated]
      }
      const allSettled = tools.every((t) => t.status !== 'running')
      return { ...msg, tools, stages: allSettled ? markDone(msg.stages, ['tools']) : msg.stages }
    }
    case 'final':
      return {
        ...msg, final: ev, status: 'done', endedAt: now,
        stages: msg.stages.map((s) => ({ ...s, state: 'done' as const })),
      }
    case 'error':
      return { ...msg, error: ev.message }
    default: // 'meta' and 'done' carry nothing the message needs
      return msg
  }
}
