import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AdminSummary } from '../types'
import { Icon } from './Icon'

const KIND: Record<string, { label: string; bar: string }> = {
  answer: { label: 'Answered with sources', bar: 'bg-teal-500' },
  no_info: { label: "Said \"I don't know\"", bar: 'bg-slate-400' },
  medical_advice: { label: 'Refused medical advice', bar: 'bg-amber-500' },
  emergency: { label: 'Emergency redirect', bar: 'bg-red-500' },
  injection: { label: 'Blocked manipulation', bar: 'bg-violet-500' },
  access: { label: 'Access needed', bar: 'bg-sky-500' },
  blocked: { label: 'Draft withheld by verifier', bar: 'bg-orange-500' },
  error: { label: 'Errors', bar: 'bg-red-600' },
  invalid: { label: 'Unsupported input', bar: 'bg-slate-300' },
  aborted: { label: 'Stopped by user', bar: 'bg-slate-300' },
}

const when = (iso: string) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })

function Card({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700/70 dark:bg-slate-800/50 ${className}`}>
      <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
      {children}
    </section>
  )
}

export function AdminDashboard() {
  const [data, setData] = useState<AdminSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updated, setUpdated] = useState<Date | null>(null)

  const load = useCallback(() => {
    api.adminSummary()
      .then((d) => { setData(d); setError(null); setUpdated(new Date()) })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000) // light auto-refresh while the dashboard is open
    return () => clearInterval(t)
  }, [load])

  const outcomes = data?.last_24h.chat_outcomes ?? []
  const total = outcomes.reduce((s, o) => s + o.n, 0)
  const max = Math.max(1, ...outcomes.map((o) => o.n))
  const blocked = outcomes.filter((o) => ['medical_advice', 'injection', 'blocked', 'emergency'].includes(o.kind)).reduce((s, o) => s + o.n, 0)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Admin dashboard</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Activity and safety signals. Question text is never stored, only length and a short hash.
            </p>
          </div>
          <button onClick={load} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:border-teal-500 dark:border-slate-700">
            <Icon name="activity" className="h-4 w-4" /> Refresh{updated && <span className="text-xs text-slate-400">· {updated.toLocaleTimeString()}</span>}
          </button>
        </div>

        {error && <p role="alert" className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-500/50 dark:bg-red-950/30 dark:text-red-200">{error}</p>}
        {data && !data.audit_ok && <p role="alert" className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/50 dark:bg-amber-950/30 dark:text-amber-200">Audit writes have failed since startup. Check the server logs.</p>}

        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ['Chat turns (24h)', total],
            ['Safety interventions', blocked],
            ['Answered with sources', outcomes.find((o) => o.kind === 'answer')?.n ?? 0],
          ].map(([label, n]) => (
            <div key={label} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700/70 dark:bg-slate-800/50">
              <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums">{n}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="What happened to each question (24h)">
            {outcomes.length === 0 ? <p className="text-sm text-slate-500">No chat activity yet.</p> : (
              <ul className="space-y-2.5">
                {outcomes.map((o) => (
                  <li key={o.kind}>
                    <div className="mb-1 flex justify-between text-sm"><span>{KIND[o.kind]?.label ?? o.kind}</span><span className="tabular-nums text-slate-500">{o.n}</span></div>
                    <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-700">
                      <div className={`h-2 rounded-full ${KIND[o.kind]?.bar ?? 'bg-slate-400'}`} style={{ width: `${(o.n / max) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Why drafts were withheld (24h)">
            {(data?.last_24h.guard_block_reasons.length ?? 0) === 0 ? <p className="text-sm text-slate-500">The verifier has not withheld any drafts.</p> : (
              <ul className="space-y-1.5 text-sm">
                {data!.last_24h.guard_block_reasons.map((r) => (
                  <li key={r.guard_reason} className="flex justify-between gap-3"><code className="truncate text-xs">{r.guard_reason}</code><span className="tabular-nums text-slate-500">{r.n}</span></li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card title="Policy sources">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500 dark:text-slate-400"><tr><th className="py-1 pr-3 font-medium">Document</th><th className="px-3 font-medium">Passages</th><th className="px-3 font-medium">Link checked</th><th className="px-3 font-medium">Ingested</th></tr></thead>
              <tbody>
                {data?.policy_sources.map((s) => (
                  <tr key={s.url} className="border-t border-slate-100 dark:border-slate-700/60">
                    <td className="py-1.5 pr-3"><a href={s.url} target="_blank" rel="noopener noreferrer" className="text-teal-700 hover:underline dark:text-teal-300">{s.title}</a></td>
                    <td className="px-3 tabular-nums">{s.chunks}</td>
                    <td className="px-3 text-slate-500">{s.verified_on ?? '—'}</td>
                    <td className="px-3 text-slate-500">{s.ingested_at ? when(s.ingested_at) : 'not yet'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Recent audit trail (append-only)">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500 dark:text-slate-400"><tr>{['Time', 'Event', 'Actor', 'Patient', 'Outcome', 'Tools'].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {data?.recent_audit.length === 0 && <tr><td colSpan={6} className="py-3 text-slate-500">Nothing recorded yet.</td></tr>}
                {data?.recent_audit.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top dark:border-slate-700/60">
                    <td className="whitespace-nowrap py-1.5 pr-3 text-slate-500">{when(r.occurred_at)}</td>
                    <td className="pr-3">{r.event_type}</td>
                    <td className="pr-3">{r.actor_label} <span className="text-xs text-slate-400">({r.actor_role})</span></td>
                    <td className="pr-3 font-mono text-xs">{r.subject_member_id ?? '—'}</td>
                    <td className="pr-3">{r.outcome_kind ?? '—'}</td>
                    <td className="font-mono text-xs">{r.tools.join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  )
}
