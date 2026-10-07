import type { Persona, SessionInfo } from '../types'
import { Icon } from './Icon'

export type Tab = 'chat' | 'dashboard'

const keyOf = (p: { persona: string; member_id?: string }) => `${p.persona}:${p.member_id ?? ''}`

export function Header({ session, personas, dark, tab, onTab, onSwitch, onToggleTheme, onLogout, onMenu }: {
  session: SessionInfo; personas: Persona[]; dark: boolean; tab: Tab
  onTab: (t: Tab) => void; onSwitch: (p: Persona) => void
  onToggleTheme: () => void; onLogout: () => void; onMenu: () => void
}) {
  // A patient is identified by role + member id; every other role by role alone.
  const current = keyOf({ persona: session.role, member_id: session.role === 'patient' ? (session.subject ?? '') : '' })

  const tabBtn = (t: Tab, label: string) => (
    <button onClick={() => onTab(t)} aria-current={tab === t ? 'page' : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${tab === t
              ? 'bg-teal-600 text-white' : 'text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-700/60'}`}>
      {label}
    </button>
  )

  return (
    <header className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white/90 px-3 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-[#0b1215]/90 sm:gap-3 sm:px-5">
      <button onClick={onMenu} aria-label="Open menu" className="rounded-lg p-2 text-slate-600 hover:bg-slate-200/70 lg:hidden dark:text-slate-300 dark:hover:bg-slate-700/60">
        <Icon name="menu" className="h-5 w-5" />
      </button>
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-600 text-white"><Icon name="shield" className="h-4 w-4" /></span>
        <span className="hidden font-semibold tracking-tight sm:block">Care Bot</span>
      </div>

      {session.capabilities.is_admin && (
        <nav aria-label="Sections" className="ml-2 flex gap-1">{tabBtn('chat', 'Chat')}{tabBtn('dashboard', 'Dashboard')}</nav>
      )}

      <div className="ml-auto flex items-center gap-2">
        <label htmlFor="persona" className="sr-only">Signed in as</label>
        <div className="relative">
          <select id="persona" value={current}
                  onChange={(e) => { const p = personas.find((x) => keyOf(x) === e.target.value); if (p) onSwitch(p) }}
                  className="max-w-[11.5rem] appearance-none truncate rounded-lg border border-slate-300 bg-white py-1.5 pl-3 pr-8 text-sm text-slate-800 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/30 sm:max-w-xs dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
            {personas.map((p) => <option key={keyOf(p)} value={keyOf(p)}>{p.label}</option>)}
          </select>
          <Icon name="chevron" className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        </div>
        <button onClick={onToggleTheme} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} title="Toggle theme"
                className="rounded-lg p-2 text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-700/60">
          <Icon name={dark ? 'sun' : 'moon'} className="h-5 w-5" />
        </button>
        <button onClick={onLogout} aria-label="Sign out" title="Sign out"
                className="rounded-lg p-2 text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-700/60">
          <Icon name="logout" className="h-5 w-5" />
        </button>
      </div>
    </header>
  )
}
