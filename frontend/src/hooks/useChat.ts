import { useCallback, useRef, useState } from 'react'
import { ApiError, streamChat } from '../api'
import { applyEvent, newBotMessage, type BotMessage, type ChatMessage } from '../chatState'
import type { StreamEvent } from '../types'

const uid = () => crypto.randomUUID()

/** Owns the conversation: sends a question, folds streamed events into the bot message, supports Stop. */
export function useChat(onAuthLost: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const conversationRef = useRef<string | null>(null)

  const patchBot = useCallback((id: string, fn: (m: BotMessage) => BotMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id && m.role === 'assistant' ? fn(m) : m)))
  }, [])

  const send = useCallback(
    async (question: string) => {
      const text = question.trim()
      if (!text || busy) return

      const botId = uid()
      setMessages((prev) => [...prev, { id: uid(), role: 'user', text }, newBotMessage(botId)])
      setBusy(true)
      const controller = new AbortController()
      abortRef.current = controller

      const onEvent = (ev: StreamEvent) => {
        if (ev.type === 'meta') conversationRef.current = ev.conversation_id // server-assigned memory key
        patchBot(botId, (m) => applyEvent(m, ev))
      }

      try {
        await streamChat(text, conversationRef.current, controller.signal, onEvent)
        // If the stream ended without a final event (connection dropped), don't leave it spinning.
        patchBot(botId, (m) =>
          m.status === 'streaming'
            ? { ...m, status: 'failed', endedAt: Date.now(), error: 'The connection closed before an answer arrived.' }
            : m,
        )
      } catch (e) {
        if ((e as Error).name === 'AbortError') {
          patchBot(botId, (m) => ({ ...m, status: 'aborted', endedAt: Date.now() }))
        } else if (e instanceof ApiError && e.status === 401) {
          onAuthLost() // session expired: back to the sign-in screen
        } else {
          // The server's own message is shown as-is (a 429 already says "Try again in Ns").
          patchBot(botId, (m) => ({ ...m, status: 'failed', endedAt: Date.now(), error: (e as Error).message }))
        }
      } finally {
        setBusy(false)
        abortRef.current = null
      }
    },
    [busy, onAuthLost, patchBot],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    conversationRef.current = null // a new conversation id means a fresh server-side memory
    setMessages([])
  }, [])

  return { messages, busy, send, stop, reset }
}
