import type { BotMessage, Stage } from '../chatState'
import type { ReplyKind, Source, ToolRun } from '../types'
import { Icon, type IconName } from './Icon'
import { Markdown } from './Markdown'

// ---------------------------------------------------------------------------- reply styling per kind
interface Tone { title: string | null; icon: IconName | null; card: string; accent: string }

const TONES: Record<ReplyKind, Tone> = {
  answer: { title: null, icon: null,
    card: 'border-slate-200 bg-white dark:border-slate-700/70 dark:bg-slate-800/60', accent: '' },
  no_info: { title: "I don't know", icon: 'help',
    card: 'border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800/40', accent: 'text-slate-600 dark:text-slate-300' },
  medical_advice: { title: 'Not medical advice', icon: 'alert',
    card: 'border-amber-300 bg-amber-50 dark:border-amber-500/50 dark:bg-amber-950/30', accent: 'text-amber-800 dark:text-amber-300' },
  emergency: { title: 'This may be an emergency', icon: 'alert',
    card: 'border-red-400 bg-red-50 dark:border-red-500/60 dark:bg-red-950/40', accent: 'text-red-700 dark:text-red-300' },
  injection: { title: 'Request declined', icon: 'shield',
    card: 'border-violet-300 bg-violet-50 dark:border-violet-500/50 dark:bg-violet-950/30', accent: 'text-violet-700 dark:text-violet-300' },
  invalid: { title: 'Message not supported', icon: 'x',
    card: 'border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800/40', accent: 'text-slate-600 dark:text-slate-300' },
  access: { title: 'Sign-in or selection needed', icon: 'lock',
    card: 'border-sky-300 bg-sky-50 dark:border-sky-500/50 dark:bg-sky-950/30', accent: 'text-sky-800 dark:text-sky-300' },
  blocked: { title: 'Answer withheld', icon: 'shield',
    card: 'border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800/40', accent: 'text-slate-600 dark:text-slate-300' },
  error: { title: 'Something went wrong', icon: 'alert',
    card: 'border-red-300 bg-red-50 dark:border-red-500/50 dark:bg-red-950/30', accent: 'text-red-700 dark:text-red-300' },
}

const BLOCK_REASONS: Record<string, string> = {
  uncited_answer: 'the draft did not cite any source',
  empty_answer: 'the draft was empty',
  prompt_leak: 'the draft tried to reveal internal instructions',
}
function explainGuard(reason: string): string {
  if (BLOCK_REASONS[reason]) return BLOCK_REASONS[reason]
  if (reason.startsWith('invented_citation')) return 'the draft cited a source that does not exist'
  if (reason.startsWith('ungrounded_dollar_amount')) return 'the draft contained a dollar amount not found in the sources'
  if (reason.startsWith('ungrounded_percentage')) return 'the draft contained a percentage not found in the sources'
  return reason
}

// ---------------------------------------------------------------------------- pieces
function ToolChip({ tool }: { tool: ToolRun }) {
  const tone =
    tool.status === 'ok' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'
    : tool.status === 'error' ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
    : 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
  return (
    <span title={tool.error ?? undefined}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] ${tone}`}>
      {tool.status === 'running' ? <Spinner className="h-3 w-3" />
        : <Icon name={tool.status === 'ok' ? 'check' : 'x'} className="h-3 w-3" />}
      {tool.name}
    </span>
  )
}

function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} animate-spin`} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function Timeline({ msg }: { msg: BotMessage }) {
  const extra = (s: Stage) => {
    if (s.id === 'tools' && msg.tools.length)
      return <div className="mt-1 flex flex-wrap gap-1.5">{msg.tools.map((t, i) => <ToolChip key={i} tool={t} />)}</div>
    if (s.id === 'retrieve' && msg.retrieval)
      return <span className="ml-1 text-slate-500 dark:text-slate-400">· {msg.retrieval.count} passage{msg.retrieval.count === 1 ? '' : 's'} found</span>
    return null
  }
  return (
    <ol className="space-y-1.5 text-sm">
      {msg.stages.map((s) => (
        <li key={s.id} className="flex items-start gap-2">
          <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center ${s.state === 'done' ? 'text-emerald-600 dark:text-emerald-400' : 'text-teal-600 dark:text-teal-300'}`}>
            {s.state === 'done' ? <Icon name="check" className="h-4 w-4" /> : <Spinner />}
          </span>
          <span className="text-slate-700 dark:text-slate-300">{s.label}{extra(s)}</span>
        </li>
      ))}
    </ol>
  )
}

function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null
  return (
    <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700">
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Sources</p>
      <ul className="space-y-1">
        {sources.map((s) => (
          <li key={s.id} className="flex items-start gap-2 text-sm">
            <Icon name={s.type === 'document' ? 'file' : 'database'} className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
            <span className="min-w-0">
              <span className="font-mono text-xs text-slate-500 dark:text-slate-400">[{s.id}] </span>
              {s.url ? (
                <a href={s.url + (s.page ? `#page=${s.page}` : '')} target="_blank" rel="noopener noreferrer"
                   className="font-medium text-teal-700 underline-offset-2 hover:underline dark:text-teal-300">
                  {s.title}{s.page ? `, p. ${s.page}` : ''}
                  <Icon name="link" className="ml-1 inline h-3 w-3" />
                </a>
              ) : (
                <span className="text-slate-700 dark:text-slate-200">{s.title}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Details({ msg }: { msg: BotMessage }) {
  const seconds = msg.endedAt ? ((msg.endedAt - msg.startedAt) / 1000).toFixed(1) : null
  const bits = [seconds && `${seconds}s`, msg.tools.length && `${msg.tools.length} record lookup${msg.tools.length > 1 ? 's' : ''}`,
    msg.retrieval && `${msg.retrieval.count} passage${msg.retrieval.count === 1 ? '' : 's'}`].filter(Boolean)
  return (
    <details className="group mt-2 text-xs text-slate-500 dark:text-slate-400">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md px-1 py-0.5 hover:bg-slate-200/60 dark:hover:bg-slate-700/60">
        <Icon name="activity" className="h-3.5 w-3.5" />
        How this was answered{bits.length ? ` · ${bits.join(' · ')}` : ''}
        <Icon name="chevron" className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 space-y-3 rounded-lg border border-slate-200 bg-white/60 p-3 dark:border-slate-700 dark:bg-slate-800/40">
        <Timeline msg={msg} />
        {msg.final?.debug?.dropped && msg.final.debug.dropped.length > 0 && (
          <p className="text-amber-700 dark:text-amber-300">
            {msg.final.debug.dropped.length} retrieved passage(s) were removed because they looked like instructions.
          </p>
        )}
        {msg.retrieval && msg.retrieval.sources.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-slate-600 dark:text-slate-300">Passages considered</p>
            <ul className="space-y-0.5">
              {msg.retrieval.sources.map((s) => (
                <li key={s.id}>
                  <span className="font-mono">[{s.id}]</span> {s.title}{s.page ? `, p. ${s.page}` : ''}
                  <span className="text-slate-400"> · distance {s.distance}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  )
}

// ---------------------------------------------------------------------------- the message
export function BotMessageView({ msg }: { msg: BotMessage }) {
  const avatar = (
    <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-600 text-white" aria-hidden="true">
      <Icon name="shield" className="h-4 w-4" />
    </div>
  )

  // --- still working
  if (msg.status === 'streaming') {
    return (
      <div className="flex gap-3" role="status" aria-live="polite" aria-label="Assistant is working">
        {avatar}
        <div className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700/70 dark:bg-slate-800/60">
          {msg.stages.length === 0 ? (
            <span className="inline-flex gap-1 text-teal-600 dark:text-teal-300" aria-hidden="true">
              <span className="dot">●</span><span className="dot">●</span><span className="dot">●</span>
            </span>
          ) : <Timeline msg={msg} />}
        </div>
      </div>
    )
  }

  // --- stopped / connection or server failure
  if (msg.status === 'aborted' || (msg.status === 'failed' && !msg.final)) {
    const aborted = msg.status === 'aborted'
    const tone = aborted ? TONES.no_info : TONES.error
    return (
      <div className="flex gap-3">
        {avatar}
        <div className={`min-w-0 flex-1 rounded-2xl border p-4 ${tone.card}`} role={aborted ? undefined : 'alert'}>
          <p className={`flex items-center gap-1.5 text-sm font-semibold ${tone.accent}`}>
            <Icon name={aborted ? 'stop' : 'alert'} className="h-4 w-4" />
            {aborted ? 'Stopped' : 'Something went wrong'}
          </p>
          {!aborted && <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">{msg.error}</p>}
        </div>
      </div>
    )
  }

  // --- finished with a reply
  const final = msg.final!
  const tone = TONES[final.kind]
  const isRefusal = final.kind !== 'answer'
  return (
    <div className="flex gap-3">
      {avatar}
      <div className="min-w-0 flex-1">
        <div className={`rounded-2xl border p-4 ${tone.card}`} role={final.kind === 'emergency' || final.kind === 'error' ? 'alert' : undefined}>
          {tone.title && (
            <p className={`mb-1 flex items-center gap-1.5 text-sm font-semibold ${tone.accent}`}>
              {tone.icon && <Icon name={tone.icon} className="h-4 w-4" />}{tone.title}
            </p>
          )}
          {final.mode === 'drug_info' && final.kind === 'answer' && (
            <p className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200">
              <Icon name="file" className="h-3.5 w-3.5" />
              FDA label information{final.debug?.drugs?.length ? `: ${final.debug.drugs.join(', ')}` : ''} · not medical advice
            </p>
          )}
          <div className={`text-[15px] ${final.kind === 'emergency' ? 'font-medium' : ''}`}>
            <Markdown text={final.text} sources={final.sources} />
          </div>
          {final.kind === 'blocked' && final.debug?.guard && (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              The verification step withheld the model's draft: {explainGuard(final.debug.guard)}.
            </p>
          )}
          {!isRefusal && <SourceList sources={final.sources} />}
        </div>
        <Details msg={msg} />
      </div>
    </div>
  )
}
