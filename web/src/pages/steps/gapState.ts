// Shared by the Gaps step and the workspace stepper: which questions exist and where each stands.
import type { Analysis, AppAnswer, Proposal } from '../../api'

export type Draft = Proposal & { state: 'pending' | 'approved' | 'rejected'; id?: string }
export type Question = { id: string; requirement: string; question: string; prefill_from?: string }
export type GapState = 'open' | 'draft' | 'pending' | 'approved' | 'no_experience'

export const REOPENED = 'kg-' // question ids for known gaps the user asked to revisit
export const FROM_REVIEW = 'hm-' // questions raised by the hiring-manager review

/** Analysis questions + known gaps the user reopened + hiring-manager questions (persisted in answers.yaml). */
export function gapQuestions(analysis: Analysis | null, answers: Record<string, AppAnswer>): Question[] {
  return [
    ...(analysis?.questions ?? []),
    ...Object.values(answers).filter((a) => a.question_id.startsWith(REOPENED) || a.question_id.startsWith(FROM_REVIEW))
      .map((a) => ({ id: a.question_id, requirement: a.requirement, question: a.question })),
  ]
}

export function gapState(answer: AppAnswer | undefined, drafts: Draft[], qid: string): GapState {
  if (answer?.status === 'approved') return 'approved'
  if (answer?.status === 'no_experience') return 'no_experience'
  if (drafts.some((d) => d.question_id === qid && d.state === 'pending')) return 'pending'
  if (answer?.status === 'draft' && answer.answer.trim()) return 'draft'
  return 'open' // unanswered, or its proposal was rejected: still a gap
}

/** Questions still waiting on the user: unanswered, answered but not turned into evidence, or awaiting approval. */
export function openGaps(questions: Question[], answers: Record<string, AppAnswer>, drafts: Draft[]) {
  return questions.filter((q) => ['open', 'draft', 'pending'].includes(gapState(answers[q.id], drafts, q.id)))
}

const words = (s: string) => new Set(s.toLowerCase().split(/[^a-z0-9+#]+/).filter((w) => w.length > 2))

/** The gap question asked about this requirement, if any (the model words them independently). */
export function questionFor(requirement: string, questions: Question[]): Question | undefined {
  const r = requirement.trim().toLowerCase()
  const exact = questions.find((q) => q.requirement.trim().toLowerCase() === r)
  if (exact) return exact
  const rw = words(requirement)
  let best: Question | undefined
  let bestScore = 0
  for (const q of questions) {
    const qw = words(q.requirement)
    const shared = [...rw].filter((w) => qw.has(w)).length
    const score = shared / Math.max(1, Math.min(rw.size, qw.size))
    if (score > bestScore) { best = q; bestScore = score }
  }
  return bestScore >= 0.6 ? best : undefined
}
