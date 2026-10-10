// Types mirror tailorbirdcv/schema.py and tailorbirdcv/api.py.

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
/** A draft profile read from a resume by the AI: nothing is saved until the user confirms it. */
export interface ImportDraft { profile: Profile; unverified: string[] }
export type SetupStep = 'welcome' | 'computer' | 'connect' | 'upload' | 'review' | 'targets' | 'design' | 'checks'
export interface SetupState {
  has_profile: boolean; completed: boolean; step: SetupStep
  draft?: ImportDraft; suggested_targets: (Partial<Targets> & { pack?: string }) | null; pages: number | null
}

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
export interface Fingerprint { sha256: string; document_id?: string | null; pdf_id?: string | null }
export interface SentCopy {
  id: string; created: string; reason: string; company?: string; role?: string; pages?: number | null; files: string[]
  fingerprints?: Record<string, Fingerprint>
}
/** Which application a PDF came from: exact file, the same PDF re-saved (its own ids), or closest text. */
export interface PdfMatch {
  app_id: string; company?: string; role?: string; status?: string; kind: 'sent' | 'build'
  snapshot: string | null; created?: string; file: string; match: 'exact' | 'document' | 'text'; score: number
}
export interface Identified extends Fingerprint { matches: PdfMatch[] }
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
  /** The company's site icon kept with the application ("favicon.png"), "" when there is none. */
  favicon?: string
  outcome?: Outcome | null; closed_at?: string | null
  /** Closed by Settings → Applications → close with no response: when, and after how many days. */
  auto_closed?: string | null; auto_close_days?: number | null
  created: string; updated: string; notes?: string; pages?: number | null; repair_rounds?: number
  guidance?: string; trim_rounds?: number; built_hash?: string
  /** How full each PDF page is (0-1) and the lines left on the last one, measured after the build. */
  fill?: { pages: number[]; room: number } | null
}
/** A cover letter's body, sentence by sentence; each kind is checked differently (factcheck.check_letter). */
export type LetterKind = 'evidence' | 'posting' | 'link'
export type LetterTone = 'formal' | 'warm' | 'direct'
export interface LetterSentence { text: string; kind: LetterKind; sources: string[] }
export interface CoverLetter { tone: LetterTone; recipient: string; paragraphs: { sentences: LetterSentence[] }[] }
export const isLetterFile = (name: string) => /_Cover_Letter\.[a-z]+$/i.test(name)

/** An AI step of one application, run as a task: it keeps going when you leave, and can be stopped.
 *  A finished one stays until the page has shown its outcome (api.clearTask). */
export type TaskKind = 'analyze' | 'proposals' | 'compose' | 'trim' | 'fill' | 'critique' | 'letter'
export interface TaskView {
  kind: TaskKind; label: string; status: 'running' | 'done' | 'failed' | 'stopped'
  started: string; finished: string | null; error: string | null
  /** Only for steps that suggest without saving (trim, fill, evidence proposals), once done. */
  result?: unknown
}
export interface TaskSummary extends TaskView { app_id: string; company: string; role: string }

export interface Application {
  id: string; meta: Meta; jd: string; analysis: Analysis | null; files: string[]
  task?: TaskView | null
  letter: CoverLetter | null; letter_report: Report | null; letter_stale: boolean
  learning_style?: boolean  // style preferences are being learned from it in the background (after applying)
  letter_notes: { id: string; text: string }[]
  tailored: Tailored | null; report: Report | null; ats: Ats | null
  answers: AppAnswer[]; edits: number
  outputs_stale: boolean
  critique: Critique | null
  sent: SentCopy[]
  length: { lines: number; budget: number } | null
  build?: { pages: number | null; too_long: boolean }
}
/** What "Trim with AI" proposes; nothing is saved until it's reviewed and saved in Review. */
export interface TrimProposal { tailored: Tailored; lines: number; budget: number; trim_rounds: number }
/** What "Fill the page" proposes: relevant unused evidence added; nothing is saved until it's saved in Review. */
export interface FillProposal { tailored: Tailored; room: number; added_lines: number }
export interface Progress {
  seniority?: string | null; requirements: number; gaps_open: number; drafted: boolean; verified: boolean | null
  critique: { verdict: CritiqueResult['verdict']['decision']; open: number; stale: boolean } | null
}
export interface AppSummary extends Meta {
  id: string; industry?: string; track?: Track; files: string[]; outputs_stale?: boolean; sent?: SentCopy | null
  progress?: Progress | null
  reached?: 'built' | 'applied' | 'interview' | 'offer' | null; reached_at?: string | null
  task?: TaskView | null
}
/** Results → Recurring gaps: one requirement of one application, as grouped into a theme (insights.py). */
/** no_experience: the date the user said they have none ("yes" when the date isn't known), or null.
 *  answered: the evidence id when the user has since answered it with approved experience (no longer a gap). */
export interface GapItem { app_id: string; text: string; priority: 'must' | 'nice'; status: 'gap' | 'partial'; no_experience: string | null; answered?: string | null }
export interface GapTheme { label: string; items: GapItem[] }
/** outdated: analysed before the profile's evidence last changed and not sent yet (worth re-analysing);
 *  outdated_sent: how many already-sent ones were. */
export interface GapsView { themes: GapTheme[] | null; created: string | null; stale: boolean; requirements: number; analysed: string[]; outdated: string[]; outdated_sent: number }
export interface EngineStatus { engine: string; ready: boolean; model?: string; detail: string }
/** The AI engines (mirrors engine.ENGINES): two subscriptions through a local app, three API keys. */
export type EngineId = 'claude-cli' | 'codex-cli' | 'anthropic-api' | 'openai-api' | 'openrouter-api'
export type KeyProvider = 'anthropic' | 'openai' | 'openrouter'
export interface ApiKeyInfo { configured: boolean; source: 'keychain' | 'environment' | 'locked' | null; masked: string | null; env?: string; prefix?: string }
export interface EngineInfo {
  id: EngineId; label: string; kind: 'subscription' | 'api'
  model_setting: 'api_model' | 'openai_model' | 'codex_model' | 'openrouter_model' | null
  default_model: string | null; provider: KeyProvider | null
}
export type PdfEngine = 'word' | 'libreoffice'
export interface PdfEngineInfo { id: PdfEngine; name: string; available: boolean; path: string | null; version: string | null }
/** pdf_engine: the user's choice (null = automatic: Word when installed); pdf_effective: what builds use now. */
export type Platform = 'macos' | 'windows' | 'linux'
/** One row of the system check. `level` says how much it matters (independent of status); `action` is what the
 *  UI can offer; `items` are sub-rows (each AI option's state). */
export interface DoctorCheck {
  id: string; label: string; status: 'ok' | 'warn' | 'error'; detail: string; fix: string
  level?: 'required' | 'recommended' | 'optional' | 'info'
  action?: { kind: 'install-browser' | 'test-pdf' | 'test-ai' | 'settings'; label: string; hint?: string }
  items?: { id: string; label: string; state: 'ready' | 'missing' | 'needs-login' | 'no-key'; detail: string }[]
}
export interface TestResult { ok: boolean; detail: string; seconds: number; engine?: string | null; alternative?: string | null }
/** Who the resume is for: steers the AI's prompts and sets the page limit (never a source of facts). */
export interface Targets { field: string; seniority: string; roles: string; region: string; spelling: 'US' | 'UK'; pages: 1 | 2 | 3; pack: string }
export interface ThemeInfo { id: string; name: string; description: string; fonts: string[]; accent: string; ink: string; rule: string; name_font: string; paper: 'letter' | 'a4' }
/** Resume sections whose heading the user can rename (Settings → Resume design). */
export type SectionKey = 'summary' | 'highlights' | 'competencies' | 'experience' | 'projects' | 'education' | 'extras'
export interface Settings {
  pdf_engine: PdfEngine | null; pdf_engines: PdfEngineInfo[]; pdf_effective: PdfEngine | null; platform?: Platform
  targets: Targets; packs: string[]; theme: string; paper: 'letter' | 'a4' | null; themes: ThemeInfo[]
  text_size?: 'standard' | 'comfortable'
  ai_engine: EngineId; api_model: string | null; openai_model: string | null; codex_model: string | null
  openrouter_model: string | null; openrouter_zdr: boolean; update_check: boolean; company_icons: boolean; learn_style: boolean
  /** Close applications still at "applied" this many days after applying, as no response (off by default). */
  auto_close: { enabled: boolean; days: number }
  hide_personal: boolean; private_address: string
  /** The user's headings ("" = the design's own, in section_defaults). */
  section_titles: Record<SectionKey, string>; section_defaults: Record<SectionKey, string>
  api_key: ApiKeyInfo; api_default_model: string; api_keys: Record<KeyProvider, ApiKeyInfo>; engines: EngineInfo[]
  keychain?: { available: boolean; backend: string | null }
}
export type SettingsPatch = { auto_close?: Partial<Settings['auto_close']>; section_titles?: Partial<Record<SectionKey, string>>; pdf_engine?: PdfEngine | null; targets?: Partial<Targets>; theme?: string; paper?: 'letter' | 'a4' | null; text_size?: 'standard' | 'comfortable'; ai_engine?: EngineId; api_model?: string | null
  openai_model?: string | null; codex_model?: string | null; openrouter_model?: string | null; openrouter_zdr?: boolean; update_check?: boolean; company_icons?: boolean; learn_style?: boolean; hide_personal?: boolean; private_address?: string }
export interface Proposal {
  question_id: string; target: string; text: string; skills: { category: string; item: string }[]
}

export const STATUSES = ['draft', 'analyzed', 'composed', 'built', 'applied', 'interview', 'offer', 'closed']
/** How a closed application ended (mirrors OUTCOMES in tailorbirdcv/store.py). */
export type Outcome = 'rejected' | 'no_response' | 'role_closed' | 'withdrew' | 'declined_offer' | 'did_not_apply' | 'accepted_offer'

/** GET /api/update: the running and latest versions, and how this copy upgrades. */
export interface UpdateStatus {
  enabled: boolean; current: string; latest: string | null; newer: boolean
  kind: 'uv-tool' | 'uv-tool-local' | 'checkout' | 'other'; command: string | null
  checked_at: string | null; error: string | null; upgrading: string | null; windows: boolean; log: boolean
  last_upgrade: { target: string; ok: boolean; at: string; error: string | null } | null
}

export class ApiError extends Error {
  status: number
  code?: string
  detail?: Record<string, unknown>
  constructor(status: number, message: string, code?: string, detail?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function req<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extraHeaders }
  if (method !== 'GET') headers['X-TailorbirdCV'] = '1'  // required by the server's cross-site guard
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'Can’t reach the TailorbirdCV server. Is `tailorbirdcv serve` still running? Your inputs are kept, so retry once it’s back.')
  }
  if (!res.ok) throw await failure(res)
  return res.status === 204 ? (undefined as T) : res.json()
}

/** The error a failed response carries (the server's message, never the submitted data). */
async function failure(res: Response): Promise<ApiError> {
  let msg = res.statusText
  let code: string | undefined
  let detail: Record<string, unknown> | undefined
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') msg = data.detail
    else if (data.detail && typeof data.detail.message === 'string') {
      msg = data.detail.message; code = data.detail.code; detail = data.detail
    } else if (Array.isArray(data.detail)) {
      // Validation errors: show what's wrong, never the submitted value (it can be a whole file).
      msg = data.detail.map((d: { msg?: string; loc?: unknown[] }) =>
        [d.loc?.slice(1).join('.'), d.msg].filter(Boolean).join(': ')).join('; ') || 'Invalid request'
    } else msg = 'Request failed'
  } catch { /* not json */ }
  if (res.status === 409 && msg.startsWith('No master profile')) window.dispatchEvent(new Event('tailorbirdcv:no-profile'))
  if (res.status === 401 && code === 'locked') window.dispatchEvent(new Event('tailorbirdcv:locked'))
  return new ApiError(res.status, msg, code, detail)
}

const OFFLINE = 'Can’t reach the TailorbirdCV server. Is `tailorbirdcv serve` still running?'

/** What a backup holds (also the summary a restore returns). */
export interface BackupSummary { created: string | null; version: string | null; files: number; applications: number; keys: string[] }
export interface RestoreResult extends BackupSummary { kept: string | null; keys_restored: string[]; keys_failed: string[] }

/** Downloads a backup .zip (saved by the browser). Returns its file name and the providers whose API keys it holds. */
async function downloadBackup(keys: boolean): Promise<{ name: string; keys: string[] }> {
  let res: Response
  try {
    res = await fetch(`/api/backup?keys=${keys}`)
  } catch {
    throw new ApiError(0, OFFLINE)
  }
  if (!res.ok) throw await failure(res)
  const name = /filename="?([^";]+)"?/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? 'TailorbirdCV-backup.zip'
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
  return { name, keys: (res.headers.get('x-backup-keys') ?? '').split(',').filter(Boolean) }
}

/** Replaces the data with a backup .zip (sent as the request body). */
async function restoreBackup(file: File): Promise<RestoreResult> {
  let res: Response
  try {
    res = await fetch('/api/restore', { method: 'POST', body: file, headers: { 'X-TailorbirdCV': '1', 'Content-Type': 'application/zip' } })
  } catch {
    throw new ApiError(0, OFFLINE)
  }
  if (!res.ok) throw await failure(res)
  return res.json()
}

export const api = {
  writeLetter: (id: string, b: { tone: LetterTone; recipient: string; notes: string[] }) =>
    req<Application>('POST', `/applications/${id}/letter`, b),
  saveLetter: (id: string, letter: CoverLetter) => req<Application>('PUT', `/applications/${id}/letter`, letter),
  buildLetter: (id: string) => req<Application>('POST', `/applications/${id}/letter/build`),
  deleteLetter: (id: string) => req<Application>('DELETE', `/applications/${id}/letter`),
  privacyPreview: () => req<{ on: boolean; text: string; hidden: Record<string, string> }>('GET', '/privacy/preview'),
  downloadBackup,
  restoreBackup,
  engine: () => req<EngineStatus>('GET', '/engine'),
  settings: () => req<Settings>('GET', '/settings'),
  doctor: (phase: 'all' | 'setup' = 'all') => req<DoctorCheck[]>('GET', `/doctor?phase=${phase}`),
  engineTest: () => req<TestResult>('POST', '/engine/test'),
  pdfTest: () => req<TestResult>('POST', '/pdf/test'),
  saveSettings: (b: SettingsPatch) => req<Settings>('PUT', '/settings', b),
  enginesInstalled: () => req<Record<'claude-cli' | 'codex-cli', boolean>>('GET', '/engine/installed'),
  saveApiKey: (key: string, provider: KeyProvider = 'anthropic') => req<Settings>('PUT', `/settings/api-key?provider=${provider}`, { key }),
  deleteApiKey: (provider: KeyProvider = 'anthropic') => req<Settings>('DELETE', `/settings/api-key?provider=${provider}`),
  profile: () => req<ProfileResponse>('GET', '/profile'),
  setup: () => req<SetupState>('GET', '/setup'),
  setupStep: (step: SetupStep) => req<SetupState>('PUT', '/setup', { step }),
  finishSetup: () => req<SetupState>('POST', '/setup/finish'),
  discardDraft: () => req<SetupState>('DELETE', '/setup/draft'),
  updateStatus: () => req<UpdateStatus>('GET', '/update'),
  checkUpdate: () => req<UpdateStatus>('POST', '/update/check'),
  upgrade: () => req<UpdateStatus>('POST', '/update/upgrade'),
  revealUpgradeLog: () => req<{ ok: boolean }>('POST', '/update/log'),
  browserStatus: () => req<{ state: 'idle' | 'running' | 'done' | 'failed'; detail: string }>('GET', '/setup/browser'),
  installBrowser: () => req<{ state: string; detail: string }>('POST', '/setup/browser'),
  importProfile: (b: { filename?: string; data?: string; text?: string; name?: string; address?: string }) =>
    req<ImportDraft & { suggested_targets: SetupState['suggested_targets']; pages: number | null }>('POST', '/profile/import', b),
  createProfile: (b: { profile: Profile; confirmed: string[] } | { blank: { name: string; location: string; headline: string } }) =>
    req<ProfileResponse>('POST', '/profile/create', b),
  saveProfile: (p: Profile, version: string) => req<ProfileResponse>('PUT', '/profile', p, { 'If-Match': version }),
  profileYaml: () => req<{ yaml: string; version: string }>('GET', '/profile/yaml'),
  saveProfileYaml: (yaml: string, version: string) =>
    req<{ yaml: string; version: string }>('PUT', '/profile/yaml', { yaml }, { 'If-Match': version }),
  addEvidence: (e: { target: string; text: string; skills: Proposal['skills']; note?: string }) =>
    req<{ id: string; evidence: Record<string, string> }>('POST', '/profile/evidence', e),

  applications: () => req<AppSummary[]>('GET', '/applications'),
  gaps: () => req<GapsView>('GET', '/insights/gaps'),
  groupGaps: () => req<GapsView>('POST', '/insights/gaps'),
  identifyPdf: (filename: string, data: string) => req<Identified>('POST', '/identify', { filename, data }),
  create: (b: { jd: string; url?: string; company?: string; role?: string }) =>
    req<{ id: string }>('POST', '/applications', b),
  get: (id: string) => req<Application>('GET', `/applications/${id}`),
  tasks: () => req<TaskSummary[]>('GET', '/tasks'),
  stopTask: (id: string) => req<{ task: TaskView | null }>('POST', `/applications/${id}/task/stop`),
  clearTask: (id: string) => req<void>('DELETE', `/applications/${id}/task`),
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
  trim: (id: string) => req<Application & { trim_proposal?: TrimProposal | null }>('POST', `/applications/${id}/trim`),
  fill: (id: string) => req<Application & { fill_proposal?: FillProposal | null }>('POST', `/applications/${id}/fill`),
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
  faviconUrl: (id: string) => `/api/applications/${id}/favicon`,
  fileUrl: (id: string, name: string, download = false) =>
    `/api/applications/${id}/files/${encodeURIComponent(name)}${download ? '?download=true' : ''}`,
}
