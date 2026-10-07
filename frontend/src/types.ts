// Shapes of everything that crosses the network. They mirror backend/app/main.py and agent/nodes.py.

export type Role = 'guest' | 'patient' | 'pharmacist' | 'admin'

export interface Persona {
  persona: Role
  label: string
  member_id?: string
  plan?: string
}

export interface SessionInfo {
  role: Role
  label: string
  subject: string | null
  subject_label: string | null
  capabilities: {
    can_read_records: boolean
    tools: string[]
    can_select_patient: boolean
    is_admin: boolean
  }
}

export interface PatientSummary {
  member_id: string
  name: string
  plan: string
}

export interface Source {
  id: string // "S1" (document passage) or "T1" (patient-records tool result)
  type: 'document' | 'records'
  title: string
  url: string | null
  page: number | null
}

export interface PolicySource {
  title: string
  publisher: string
  url: string
  doc_type: string
  description: string | null
  verified_on: string | null
  category: 'coverage_policy' | 'drug_label'
}

/** What kind of reply this is. The UI styles each one differently. */
export type ReplyKind =
  | 'answer'
  | 'no_info'
  | 'medical_advice'
  | 'emergency'
  | 'injection'
  | 'invalid'
  | 'access'
  | 'blocked'
  | 'error'

export interface ToolRun {
  name: string
  status: 'running' | 'ok' | 'error'
  error?: string | null
}

export interface FinalEvent {
  type: 'final'
  text: string
  kind: ReplyKind
  citations: string[]
  sources: Source[]
  tools: { name: string; status: string }[]
  mode?: 'drug_info' | 'coverage'
  debug?: { intent?: string | null; guard?: string; dropped?: string[]; drugs?: string[] }
  conversation_id?: string
}

export interface RetrievalInfo {
  count: number
  sources: { id: string; title: string; url: string; page: number | null; distance: number }[]
}

export type StreamEvent =
  | { type: 'meta'; conversation_id: string }
  | { type: 'status'; stage: string; message: string }
  | ({ type: 'retrieval' } & RetrievalInfo)
  | { type: 'tool'; name: string; status: 'running' | 'ok' | 'error'; error?: string | null }
  | FinalEvent
  | { type: 'error'; message: string }
  | { type: 'done' }

export interface AdminSummary {
  last_24h: {
    chat_outcomes: { kind: string; n: number }[]
    guard_block_reasons: { guard_reason: string; n: number }[]
  }
  recent_audit: {
    occurred_at: string
    event_type: string
    actor_role: string
    actor_label: string
    subject_member_id: string | null
    outcome_kind: string | null
    tools: string[]
  }[]
  policy_sources: { title: string; url: string; verified_on: string | null; ingested_at: string | null; chunks: number; category: string }[]
  audit_ok: boolean
}
