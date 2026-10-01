// Types mirror autocv/schema.py and autocv/api.py.

export type Track = 'manager' | 'ic' | 'hybrid'

export interface Claim { text: string; sources: string[] }
export interface TailoredRole {
  role: string
  scope?: Claim | null
  bullets: Claim[]
  sub_roles: { id: string; text?: Claim | null }[]
}
export interface Tailored {
  headline: string
  summary?: Claim | null
  highlights: Claim[]
  competencies: { label: string; items: string[] }[]
  experience: TailoredRole[]
  projects: { id: string; text?: Claim | null }[]
  education: string[]
  extras: string[]
}

export interface Evidence {
  id: string; text: string; source?: string; in_base_resume?: boolean; tags?: string[]; note?: string
}
export interface LeadItem { id: string; label: string; text: string; source?: string; in_base_resume?: boolean }
export interface Role {
  id: string; employer: string; location: string; title: string; dates: string
  scope?: Evidence & { italic?: boolean }
  achievements: Evidence[]
  sub_roles: LeadItem[]
}
export interface Profile {
  contact: { name: string; location: string; phone?: string; email?: string; links: { text: string; url: string }[] }
  headlines: { id: string; text: string; tracks: Track[] }[]
  summary_facts: Evidence[]
  highlights: Evidence[]
  skills: { category: string; items: string[] }[]
  roles: Role[]
  projects: LeadItem[]
  education: LeadItem[]
  extras: LeadItem[]
  synonyms: string[][]
  vocabulary: string[]
}
export interface ProfileResponse { profile: Profile; evidence: Record<string, string> }

export interface Requirement {
  text: string; priority: 'must' | 'nice'; status: 'strong' | 'partial' | 'gap'; evidence: string[]; note: string
}
export interface Analysis {
  company: string; role: string; industry: string; track: Track; seniority: string; location: string
  summary: string
  requirements: Requirement[]
  keywords: { term: string; priority: 'must' | 'nice'; aliases: string[] }[]
  questions: { id: string; requirement: string; question: string; prefill_from?: string }[]
  known_gaps?: { requirement: string; knowledge_id: string }[]
}
export type AnswerStatus = 'draft' | 'no_experience' | 'approved' | 'rejected'
export interface AppAnswer {
  question_id: string; requirement: string; question: string; answer: string
  status: AnswerStatus; evidence_id?: string | null; prefill_from?: string | null
}
export interface KnowledgeAnswer {
  id: string; topic: string; question: string; answer: string; kind: 'experience' | 'no_experience'
  evidence_id?: string | null; app_id?: string | null; company?: string | null; date: string
}
export interface Preference {
  id: string; text: string; rationale: string; status: 'proposed' | 'active' | 'dismissed'
  source_app?: string | null; date: string
}
export interface Knowledge { answers: KnowledgeAnswer[]; preferences: Preference[] }
export interface Issue { where: string; message: string }
export interface Report { ok: boolean; errors: Issue[]; warnings: Issue[] }
export interface Ats {
  words: number
  coverage: Record<'must' | 'nice', { hit: number; total: number }>
  keywords: { term: string; priority: string; status: 'in_resume' | 'unused' | 'gap' }[]
}
export interface Meta {
  company: string; role: string; url?: string | null; status: string
  created: string; updated: string; notes?: string; pages?: number | null; repair_rounds?: number
  guidance?: string
}
export interface Application {
  id: string; meta: Meta; jd: string; analysis: Analysis | null; files: string[]
  tailored: Tailored | null; report: Report | null; ats: Ats | null
  answers: AppAnswer[]; edits: number
  build?: { pages: number | null; too_long: boolean }
}
export interface AppSummary extends Meta { id: string; industry?: string; track?: Track; files: string[] }
export interface EngineStatus { engine: string; ready: boolean; model?: string; detail: string }
export interface Proposal {
  question_id: string; target: string; text: string; skills: { category: string; item: string }[]
}

export const STATUSES = ['draft', 'analyzed', 'composed', 'built', 'applied', 'interview', 'offer', 'rejected', 'withdrawn']

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  engine: () => req<EngineStatus>('GET', '/engine'),
  profile: () => req<ProfileResponse>('GET', '/profile'),
  saveProfile: (p: Profile) => req<ProfileResponse>('PUT', '/profile', p),
  profileYaml: () => req<{ yaml: string }>('GET', '/profile/yaml'),
  saveProfileYaml: (yaml: string) => req<{ yaml: string }>('PUT', '/profile/yaml', { yaml }),
  addEvidence: (e: { target: string; text: string; skills: Proposal['skills']; note?: string }) =>
    req<{ id: string; evidence: Record<string, string> }>('POST', '/profile/evidence', e),

  applications: () => req<AppSummary[]>('GET', '/applications'),
  create: (b: { jd: string; url?: string; company?: string; role?: string }) =>
    req<{ id: string }>('POST', '/applications', b),
  get: (id: string) => req<Application>('GET', `/applications/${id}`),
  patch: (id: string, b: Partial<Meta>) => req<Meta>('PATCH', `/applications/${id}`, b),
  remove: (id: string) => req<void>('DELETE', `/applications/${id}`),
  analyze: (id: string) => req<Application>('POST', `/applications/${id}/analyze`),
  proposals: (id: string, answers: { question_id: string; question: string; answer: string }[]) =>
    req<Proposal[]>('POST', `/applications/${id}/proposals`, answers),
  compose: (id: string, guidance: string) => req<Application>('POST', `/applications/${id}/compose`, { guidance }),
  saveTailored: (id: string, t: Tailored) => req<Application>('PUT', `/applications/${id}/tailored`, t),
  build: (id: string) => req<Application>('POST', `/applications/${id}/build`),
  saveAnswers: (id: string, answers: AppAnswer[]) => req<AppAnswer[]>('PUT', `/applications/${id}/answers`, answers),
  knowledge: () => req<Knowledge>('GET', '/knowledge'),
  saveKnowledge: (k: Knowledge) => req<Knowledge>('PUT', '/knowledge', k),
  suggestPreferences: (id: string) =>
    req<{ edits: number; proposed: number; knowledge: Knowledge }>('POST', `/applications/${id}/preferences`),
  fileUrl: (id: string, name: string, download = false) =>
    `/api/applications/${id}/files/${encodeURIComponent(name)}${download ? '?download=true' : ''}`,
}
