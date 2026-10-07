import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { AdminDashboard } from './components/AdminDashboard'
import { ChatView } from './components/ChatView'
import { Header, type Tab } from './components/Header'
import { Landing } from './components/Landing'
import { Sidebar } from './components/Sidebar'
import { useChat } from './hooks/useChat'
import { useSession } from './hooks/useSession'
import { useTheme } from './hooks/useTheme'
import type { PatientSummary, Persona, PolicySource, Role } from './types'

export default function App() {
  const theme = useTheme()
  const auth = useSession()
  const chat = useChat(auth.expire) // if the session expires mid-chat, drop back to the sign-in screen
  const { reset } = chat

  const [personas, setPersonas] = useState<Persona[]>([])
  const [notice, setNotice] = useState('')
  const [personasError, setPersonasError] = useState<string | null>(null)
  const [sources, setSources] = useState<PolicySource[]>([])
  const [patients, setPatients] = useState<PatientSummary[]>([])
  const [tabChoice, setTabChoice] = useState<Partial<Record<Role, Tab>>>({})
  const [menuOpen, setMenuOpen] = useState(false)

  const session = auth.session
  const role = session?.role
  const scope = session ? `${session.role}:${session.subject ?? ''}` : 'none'
  // Derived, not stored: admins land on the dashboard, everyone else on chat, unless they picked a tab.
  const tab: Tab = (role && tabChoice[role]) || (role === 'admin' ? 'dashboard' : 'chat')
  const setTab = (t: Tab) => role && setTabChoice((prev) => ({ ...prev, [role]: t }))

  // Public reference data. A failure is SHOWN (with a Retry button), never swallowed.
  const loadPublicData = useCallback(() => {
    api.personas()
      .then((r) => { setPersonas(r.personas); setNotice(r.demo_notice) })
      .catch((e: Error) => setPersonasError(e.message))
    api.sources().then((r) => setSources(r.sources)).catch(() => {})
  }, [])
  useEffect(() => { loadPublicData() }, [loadPublicData])

  // A different person, role or patient in scope means a different conversation (the server scopes memory the same way).
  useEffect(() => { reset() }, [scope, reset])

  // The patient list is only needed (and only allowed) for pharmacists.
  useEffect(() => {
    if (role === 'pharmacist') api.patients().then((r) => setPatients(r.patients)).catch(() => {})
  }, [role])

  const pick = (p: Persona) => auth.login(p.persona, p.member_id)

  if (auth.loading) {
    return <div className="flex h-full items-center justify-center text-sm text-slate-500" role="status">Loading…</div>
  }

  if (!session) {
    return <div className="h-full overflow-y-auto"><Landing personas={personas} notice={notice} error={auth.error ?? personasError} onPick={pick} onRetry={() => { setPersonasError(null); loadPublicData() }} /></div>
  }

  return (
    <div className="flex h-full flex-col">
      <Header
        session={session} personas={personas} dark={theme.dark} tab={tab} onTab={setTab}
        onSwitch={pick} onToggleTheme={theme.toggle} onLogout={auth.logout} onMenu={() => setMenuOpen(true)}
      />
      {auth.error && (
        <div role="alert" className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
          <span>{auth.error}</span>
          <button onClick={auth.clearError} className="underline">Dismiss</button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          session={session} personas={personas} patients={patients} sources={sources}
          open={menuOpen} onClose={() => setMenuOpen(false)}
          onSelectPatient={auth.selectPatient} onNewChat={reset}
        />
        <main className="flex min-w-0 flex-1 flex-col">
          {tab === 'dashboard' && session.capabilities.is_admin
            ? <AdminDashboard />
            : <ChatView session={session} messages={chat.messages} busy={chat.busy} onSend={chat.send} onStop={chat.stop} />}
        </main>
      </div>
    </div>
  )
}
