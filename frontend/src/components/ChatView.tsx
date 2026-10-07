import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { ChatMessage } from '../chatState'
import type { Role, SessionInfo } from '../types'
import { BotMessageView } from './BotMessageView'
import { Icon } from './Icon'

const MAX_CHARS = 1000 // matches the server's input guard

const SUGGESTIONS: Record<Role, string[]> = {
  guest: [
    'What is prior authorization?',
    'What is the Part D deductible for 2026?',
    'Compare the premiums and deductibles of all plans',
    'What are the side effects of lisinopril?',
  ],
  patient: [
    'What are my active prescriptions and their copays?',
    'Which of my medications need prior authorization?',
    "What is my plan's deductible and out-of-pocket maximum?",
    'What is Jardiance used for?',
  ],
  pharmacist: [
    "What are this patient's active prescriptions and copays?",
    'Which of their medications need prior authorization?',
    'What plan is this patient on?',
    'What are the side effects of atorvastatin?',
  ],
  admin: [
    'What is prior authorization?',
    'Compare the premiums and deductibles of all plans',
    'What are the warnings for Eliquis?',
  ],
}

const WELCOME: Record<Role, string> = {
  guest: 'Ask about insurance rules and plans, or what an official FDA drug label says. Sign in as a patient to look up personal records.',
  patient: 'Ask about your prescriptions, copays and coverage, how insurance rules work, or what an FDA drug label says.',
  pharmacist: 'Select a patient in the sidebar, then ask about their prescriptions and coverage.',
  admin: 'Admins can ask policy and plan questions here. Patient records are not available through chat.',
}

function Composer({ busy, onSend, onStop, placeholder }: {
  busy: boolean; onSend: (q: string) => void; onStop: () => void; placeholder: string
}) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  // Auto-grow the textarea up to ~6 lines.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [value])

  const submit = () => {
    if (!value.trim() || busy) return
    onSend(value)
    setValue('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-slate-200 bg-white/80 p-3 backdrop-blur dark:border-slate-800 dark:bg-[#0b1215]/80 sm:p-4">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <div className="relative flex-1">
          <label htmlFor="composer" className="sr-only">Your question</label>
          <textarea
            id="composer" ref={ref} rows={1} value={value} maxLength={MAX_CHARS} placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)} onKeyDown={onKeyDown}
            className="block max-h-40 w-full resize-none rounded-2xl border border-slate-300 bg-white px-4 py-3 pr-14 text-[15px] text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/30 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
          {value.length > MAX_CHARS * 0.8 && (
            <span className={`pointer-events-none absolute right-3 top-1 text-[11px] ${value.length >= MAX_CHARS ? 'text-red-600' : 'text-slate-400'}`}>
              {value.length}/{MAX_CHARS}
            </span>
          )}
        </div>
        {busy ? (
          <button onClick={onStop} aria-label="Stop generating" title="Stop"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-800 text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-white">
            <Icon name="stop" className="h-5 w-5" />
          </button>
        ) : (
          <button onClick={submit} disabled={!value.trim()} aria-label="Send message" title="Send (Enter)"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-teal-600 text-white hover:bg-teal-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500 disabled:cursor-not-allowed disabled:opacity-40">
            <Icon name="send" className="h-5 w-5" />
          </button>
        )}
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-500 dark:text-slate-400">
        AI assistant, not a doctor. It answers only from the cited documents and records. For medical questions, consult a doctor or pharmacist.
      </p>
    </div>
  )
}

export function ChatView({ session, messages, busy, onSend, onStop }: {
  session: SessionInfo; messages: ChatMessage[]; busy: boolean
  onSend: (q: string) => void; onStop: () => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  // "Stay pinned to the bottom unless the user scrolled up to re-read something."
  // We infer the user's intent from scroll events, so OUR OWN scrolling must never fire them while
  // the content is still growing (a smooth-scroll animation did exactly that and un-pinned the view).
  // Hence: instant jumps, driven by a ResizeObserver, so any growth (streamed stages, the final
  // answer, an opened details panel) keeps the view at the bottom.
  const onScroll = () => {
    const el = scroller.current
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }
  useEffect(() => {
    const el = scroller.current
    const inner = content.current
    if (!el || !inner) return
    const observer = new ResizeObserver(() => {
      if (stickToBottom.current) el.scrollTop = el.scrollHeight
    })
    observer.observe(inner)
    return () => observer.disconnect()
  }, [])
  // A new message (the user's own send) always re-pins, so they see their question and the reply.
  useEffect(() => { stickToBottom.current = true }, [messages.length])

  const needsPatient = session.role === 'pharmacist' && !session.subject
  const who = session.subject_label ?? session.label

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {needsPatient && (
        <div className="border-b border-sky-200 bg-sky-50 px-4 py-2 text-center text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
          <Icon name="lock" className="mr-1 inline h-4 w-4" />
          Select a patient in the sidebar to look up their records. General policy questions work without one.
        </div>
      )}
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6">
        <div ref={content} className="mx-auto max-w-3xl space-y-5">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center pt-8 text-center sm:pt-16">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-600 text-white shadow-lg shadow-teal-600/20">
                <Icon name="shield" className="h-7 w-7" />
              </div>
              <h2 className="text-2xl font-semibold tracking-tight">
                {session.role === 'patient' ? `Hello, ${who.split(' ')[0]}` : 'How can I help?'}
              </h2>
              <p className="mt-2 max-w-md text-sm text-slate-600 dark:text-slate-400">{WELCOME[session.role]}</p>
              <div className="mt-6 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
                {SUGGESTIONS[session.role].map((s) => (
                  <button key={s} onClick={() => onSend(s)}
                          className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 shadow-sm transition hover:border-teal-400 hover:bg-teal-50/60 focus-visible:outline-2 focus-visible:outline-teal-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:border-teal-500 dark:hover:bg-slate-800">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-teal-600 px-4 py-2.5 text-[15px] text-white">
                    {m.text}
                  </div>
                </div>
              ) : (
                <BotMessageView key={m.id} msg={m} />
              ),
            )
          )}
        </div>
      </div>
      <Composer
        busy={busy} onSend={onSend} onStop={onStop}
        placeholder={needsPatient ? 'Ask a general question, or select a patient first…' : 'Ask about coverage, copays, prescriptions, policies…'}
      />
    </div>
  )
}
