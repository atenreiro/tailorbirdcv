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
  retired_ids?: string[]
}
export interface ProfileResponse { profile: Profile; evidence: Record<string, string>; version: string }

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
export interface Knowledge { answers: KnowledgeAnswer[]; preferences: Preference[]; retired_ids?: string[]; version?: string }
export interface Issue { where: string; message: string }
export interface SentCopy {
  id: string; created: string; reason: string; company?: string; role?: string; pages?: number | null; files: string[]
}
export interface HistoryEntry { id: string; time: string; cause: string; size: number }
export interface HistoryDiff { id: string; yaml: string; summary: string[]; diff: string }
export type HistoryKind = 'profile' | 'knowledge'
export type ScoreKey = 'fit' | 'impact' | 'clarity' | 'seniority'
export interface CritiqueIssue {
  id: string; where: string; kind: string; severity: 'high' | 'medium' | 'low'; problem: string
  action: 'rewrite' | 'remove' | 'move_to_top' | 'advice'
  rewrite: Claim | null; question: string | null; note_for: 'cover_letter' | 'interview' | null
  original?: Claim; blocked?: string
}
export interface CritiqueResult {
  verdict: { decision: 'interview' | 'borderline' | 'pass'; reason: string }
  scores: Record<ScoreKey, { score: number; why: string }>
  skim: { takeaway: string; lands: string[]; misses: string[] }
  strengths: { where: string; why: string }[]
  issues: CritiqueIssue[]
}
export interface Critique {
  latest: CritiqueResult; created: string; previous_scores: CritiqueResult['scores'] | null
  decisions: Record<string, 'accepted' | 'rejected'>; stale: boolean
}
export interface Report { ok: boolean; errors: Issue[]; warnings: Issue[] }
export interface Ats {
  words: number
  coverage: Record<'must' | 'nice', { hit: number; total: number }>
  keywords: { term: string; priority: string; status: 'in_resume' | 'unused' | 'gap' }[]
}
export interface Meta {
  company: string; role: string; url?: string | null; status: string
  created: string; updated: string; notes?: string; pages?: number | null; repair_rounds?: number
  guidance?: string; trim_rounds?: number; built_hash?: string
}
export interface Application {
  id: string; meta: Meta; jd: string; analysis: Analysis | null; files: string[]
  tailored: Tailored | null; report: Report | null; ats: Ats | null
  answers: AppAnswer[]; edits: number
  outputs_stale: boolean
  critique: Critique | null
  sent: SentCopy[]
  length: { lines: number; budget: number } | null
  build?: { pages: number | null; too_long: boolean }
}
export interface Progress {
  seniority?: string | null; requirements: number; gaps_open: number; drafted: boolean; verified: boolean | null
  critique: { verdict: CritiqueResult['verdict']['decision']; open: number; stale: boolean } | null
}
export interface AppSummary extends Meta {
  id: string; industry?: string; track?: Track; files: string[]; outputs_stale?: boolean; sent?: SentCopy | null
  progress?: Progress | null
  reached?: 'built' | 'applied' | 'interview' | 'offer' | null; reached_at?: string | null
}
export interface EngineStatus { engine: string; ready: boolean; model?: string; detail: string }
export interface Proposal {
  question_id: string; target: string; text: string; skills: { category: string; item: string }[]
}

export const STATUSES = ['draft', 'analyzed', 'composed', 'built', 'applied', 'interview', 'offer', 'rejected', 'withdrawn']

export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function req<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extraHeaders }
  if (method !== 'GET') headers['X-AutoCV'] = '1'  // required by the server's cross-site guard
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'Can’t reach the AutoCV server. Is `uv run autocv serve` still running? Your inputs are kept, so retry once it’s back.')
  }
  if (!res.ok) {
    let msg = res.statusText
    let code: string | undefined
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') msg = data.detail
      else if (data.detail && typeof data.detail.message === 'string') { msg = data.detail.message; code = data.detail.code }
      else msg = JSON.stringify(data.detail)
    } catch { /* not json */ }
    throw new ApiError(res.status, msg, code)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  engine: () => req<EngineStatus>('GET', '/engine'),
  profile: () => req<ProfileResponse>('GET', '/profile'),
  saveProfile: (p: Profile, version: string) => req<ProfileResponse>('PUT', '/profile', p, { 'If-Match': version }),
  profileYaml: () => req<{ yaml: string; version: string }>('GET', '/profile/yaml'),
  saveProfileYaml: (yaml: string, version: string) =>
    req<{ yaml: string; version: string }>('PUT', '/profile/yaml', { yaml }, { 'If-Match': version }),
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
  saveKnowledge: ({ version, ...k }: Knowledge) =>
    req<Knowledge>('PUT', '/knowledge', k, version ? { 'If-Match': version } : {}),
  trim: (id: string) => req<Application>('POST', `/applications/${id}/trim`),
  critique: (id: string) => req<Application>('POST', `/applications/${id}/critique`),
  reveal: (id: string, snapshot?: string) =>
    req<void>('POST', `/applications/${id}/reveal${snapshot ? `?snapshot=${encodeURIComponent(snapshot)}` : ''}`),
  freeze: (id: string, opts: { build?: boolean; markApplied?: boolean } = {}) =>
    req<Application>('POST', `/applications/${id}/freeze?build=${!!opts.build}&mark_applied=${!!opts.markApplied}`),
  sentFileUrl: (id: string, snapshot: string, name: string, download = false) =>
    `/api/applications/${id}/sent/${encodeURIComponent(snapshot)}/${encodeURIComponent(name)}${download ? '?download=true' : ''}`,
  history: (kind: HistoryKind) => req<HistoryEntry[]>('GET', `/history/${kind}`),
  historyDiff: (kind: HistoryKind, id: string) => req<HistoryDiff>('GET', `/history/${kind}/${encodeURIComponent(id)}`),
  restore: (kind: HistoryKind, id: string) => req<unknown>('POST', `/history/${kind}/${encodeURIComponent(id)}/restore`),
  saveCritiqueDecisions: (id: string, decisions: Record<string, 'accepted' | 'rejected'>) =>
    req<Critique>('PUT', `/applications/${id}/critique/decisions`, { decisions }),
  suggestPreferences: (id: string) =>
    req<{ edits: number; proposed: number; knowledge: Knowledge }>('POST', `/applications/${id}/preferences`),
  fileUrl: (id: string, name: string, download = false) =>
    `/api/applications/${id}/files/${encodeURIComponent(name)}${download ? '?download=true' : ''}`,
}
