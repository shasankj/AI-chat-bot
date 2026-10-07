import type { PatientSummary, Persona, PolicySource, SessionInfo } from '../types'
import { Icon } from './Icon'

const ROLE_BADGE: Record<string, string> = {
  guest: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  patient: 'bg-teal-100 text-teal-800 dark:bg-teal-900/50 dark:text-teal-200',
  pharmacist: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200',
  admin: 'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200',
}

const TOOL_LABELS: Record<string, string> = {
  get_patient_profile: 'Patient profile',
  list_prescriptions: 'Prescriptions',
  get_drug_coverage: 'Drug coverage',
  get_plan_details: 'Plan catalog',
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="px-4 py-3">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title}</h3>
      {children}
    </section>
  )
}

function SourceGroup({ title, sources, open = false }: { title: string; sources: PolicySource[]; open?: boolean }) {
  if (sources.length === 0) return null
  return (
    <details open={open} className="group mb-2">
      <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-1.5 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800">
        <span>{title} <span className="text-xs font-normal text-slate-400">({sources.length})</span></span>
        <Icon name="chevron" className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      <ul className="mt-1 space-y-1">
        {sources.map((s) => (
          <li key={s.url}>
            <a href={s.url} target="_blank" rel="noopener noreferrer"
               className="group/link flex items-start gap-2 rounded-lg p-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
              <Icon name="file" className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <span className="min-w-0">
                <span className="block leading-snug text-slate-800 group-hover/link:text-teal-700 dark:text-slate-200 dark:group-hover/link:text-teal-300">{s.title}</span>
                <span className="block text-xs text-slate-500 dark:text-slate-400">{s.publisher}{s.verified_on ? ` · checked ${s.verified_on}` : ''}</span>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </details>
  )
}

export function Sidebar({ session, personas, patients, sources, open, onClose, onSelectPatient, onNewChat }: {
  session: SessionInfo; personas: Persona[]; patients: PatientSummary[]; sources: PolicySource[]
  open: boolean; onClose: () => void; onSelectPatient: (id: string | null) => void; onNewChat: () => void
}) {
  const plan = session.role === 'patient' ? personas.find((p) => p.member_id === session.subject)?.plan : undefined

  return (
    <>
      {open && <div className="fixed inset-0 z-20 bg-slate-900/40 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside aria-label="Context"
             className={`fixed inset-y-0 left-0 z-30 flex w-80 max-w-[85vw] flex-col overflow-y-auto border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-[#0e171b] lg:static lg:z-0 lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800 lg:hidden">
          <span className="font-semibold">Menu</span>
          <button onClick={onClose} aria-label="Close menu" className="rounded-lg p-1.5 hover:bg-slate-200/70 dark:hover:bg-slate-700/60"><Icon name="x" className="h-5 w-5" /></button>
        </div>

        <div className="px-4 pt-4">
          <button onClick={() => { onNewChat(); onClose() }}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:border-teal-500 hover:text-teal-700 focus-visible:outline-2 focus-visible:outline-teal-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:text-teal-300">
            <Icon name="plus" className="h-4 w-4" /> New conversation
          </button>
        </div>

        <Section title="Signed in as">
          <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
            <p className="font-medium">{session.label}</p>
            <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${ROLE_BADGE[session.role]}`}>{session.role}</span>
            {plan && <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{plan}</p>}
          </div>
        </Section>

        {session.capabilities.can_select_patient && (
          <Section title="Patient in scope">
            <label htmlFor="patient" className="sr-only">Select a patient</label>
            <div className="relative">
              <select id="patient" value={session.subject ?? ''}
                      onChange={(e) => onSelectPatient(e.target.value || null)}
                      className="w-full appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-3 pr-8 text-sm outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/30 dark:border-slate-700 dark:bg-slate-900">
                <option value="">None selected</option>
                {patients.map((p) => <option key={p.member_id} value={p.member_id}>{p.name} ({p.member_id})</option>)}
              </select>
              <Icon name="chevron" className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            </div>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              Each lookup is recorded in the audit log. Switching patients starts a fresh conversation.
            </p>
          </Section>
        )}

        <Section title="This account can use">
          <ul className="space-y-1.5 text-sm">
            <li className="flex items-center gap-2"><Icon name="file" className="h-4 w-4 text-teal-600" />Policy documents</li>
            {session.capabilities.tools.map((t) => {
              const patientOnly = t !== 'get_plan_details'
              const usable = !patientOnly || session.capabilities.can_read_records
              return (
                <li key={t} className={`flex items-center gap-2 ${usable ? '' : 'text-slate-400 line-through dark:text-slate-500'}`}>
                  <Icon name="database" className={`h-4 w-4 ${usable ? 'text-sky-600' : ''}`} />
                  {TOOL_LABELS[t] ?? t}
                  {!usable && <span className="text-[11px] no-underline">(needs a patient)</span>}
                </li>
              )
            })}
          </ul>
        </Section>

        <Section title="References">
          <SourceGroup title="Coverage rules (Medicare)" sources={sources.filter((s) => s.category !== 'drug_label')} open />
          <SourceGroup title="FDA drug labels" sources={sources.filter((s) => s.category === 'drug_label')} />
        </Section>

        <div className="mt-auto px-4 py-4 text-[11px] leading-relaxed text-slate-500 dark:text-slate-500">
          Synthetic demo data. Not real authentication. Policy documents are general Medicare guidance, not the rules of any specific plan.
        </div>
      </aside>
    </>
  )
}
