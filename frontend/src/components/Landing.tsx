import type { Persona } from '../types'
import { Icon, type IconName } from './Icon'

function Card({ icon, title, subtitle, onClick }: { icon: IconName; title: string; subtitle: string; onClick: () => void }) {
  return (
    <button onClick={onClick}
            className="group flex items-start gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-teal-400 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500 dark:border-slate-700 dark:bg-slate-800/60 dark:hover:border-teal-500">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-700 group-hover:bg-teal-100 dark:bg-teal-900/40 dark:text-teal-300">
        <Icon name={icon} className="h-5 w-5" />
      </span>
      <span className="min-w-0">
        <span className="block font-medium text-slate-900 dark:text-slate-100">{title}</span>
        <span className="block text-sm text-slate-500 dark:text-slate-400">{subtitle}</span>
      </span>
    </button>
  )
}

export function Landing({ personas, notice, error, onPick, onRetry }: {
  personas: Persona[]; notice: string; error: string | null; onPick: (p: Persona) => void; onRetry: () => void
}) {
  const guest = personas.find((p) => p.persona === 'guest')
  const patients = personas.filter((p) => p.persona === 'patient')
  const staff = personas.filter((p) => p.persona === 'pharmacist' || p.persona === 'admin')

  return (
    <div className="mx-auto flex min-h-full max-w-4xl flex-col px-5 py-10 sm:py-14">
      <div className="text-center">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-600 text-white shadow-lg shadow-teal-600/25">
          <Icon name="shield" className="h-7 w-7" />
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Care Bot</h1>
        <p className="mx-auto mt-3 max-w-xl text-slate-600 dark:text-slate-400">
          An insurance and pharmacy assistant that answers only from cited policy documents, FDA drug labels and
          patient records. It never gives medical advice, and says "I don't know" when it can't.
        </p>
        <p className="mx-auto mt-4 inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
          <Icon name="alert" className="h-3.5 w-3.5" />
          {notice || 'Demo sign-in with synthetic people.'}
        </p>
      </div>

      {error && (
        <div role="alert" className="mx-auto mt-6 max-w-xl rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-500/50 dark:bg-red-950/30 dark:text-red-200">
          <p>{error}</p>
          <button onClick={onRetry} className="mt-2 rounded-lg border border-red-400 px-3 py-1 font-medium hover:bg-red-100 dark:border-red-500/60 dark:hover:bg-red-900/40">
            Try again
          </button>
        </div>
      )}

      {personas.length === 0 && !error && <p className="mt-10 text-center text-sm text-slate-500" role="status">Loading…</p>}

      {guest && (
        <section className="mt-10">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Explore</h2>
          <Card icon="file" title="Continue as guest" subtitle="Policy documents and public plan information. No personal records." onClick={() => onPick(guest)} />
        </section>
      )}

      {patients.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Sign in as a patient</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {patients.map((p) => (
              <Card key={p.member_id} icon="user" title={p.label.replace('Patient: ', '')} subtitle={p.plan ?? ''} onClick={() => onPick(p)} />
            ))}
          </div>
        </section>
      )}

      {staff.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Staff</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {staff.map((p) => (
              <Card key={p.persona} icon={p.persona === 'admin' ? 'activity' : 'heart'} title={p.label}
                    subtitle={p.persona === 'admin' ? 'Dashboard, audit log and guardrail activity. No patient records.' : 'Look up any patient you select, with every access logged.'}
                    onClick={() => onPick(p)} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
