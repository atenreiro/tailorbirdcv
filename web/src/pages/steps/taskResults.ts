// How an AI step's result lands in the page, shared by the step that started it and by the application page
// when it finds the result of a step that finished while you were elsewhere (Workspace: background tasks).
import type { Application, FillProposal, Proposal, TrimProposal } from '../../api'
import type { StepMemo } from '../Workspace'
import type { Draft } from './gapState'

export const TRIM_NOTHING = 'The AI couldn’t find anything to cut without changing the facts. Trim it yourself in Review: remove the least relevant lines, then rebuild.'
export const FILL_NOTHING = 'The AI found nothing relevant to add that fits without changing the facts. You can add evidence yourself in Review (“+ add … from evidence”).'

/** An AI trim opens in Review as unsaved edits: nothing is saved until you Save & check there. */
export function withTrim(m: StepMemo, proposal: TrimProposal, app: Application): StepMemo {
  const before = app.length ? `~${app.length.lines}` : 'the current length'
  return {
    ...m,
    review: {
      draft: proposal.tailored, rev: (m.review?.rev ?? 0) + 1,
      notice: `AI trim suggestions — review the changes, then Save & check. Estimated ${before} → ~${proposal.lines} of ${proposal.budget} lines; edited lines are marked with a dot. Nothing is saved until you save, and Discard keeps the current version.`,
    },
  }
}

/** AI additions to fill the last page open in Review as unsaved edits, like a trim. */
export function withFill(m: StepMemo, proposal: FillProposal): StepMemo {
  return {
    ...m,
    review: {
      draft: proposal.tailored, rev: (m.review?.rev ?? 0) + 1,
      notice: `AI additions to fill the last page — about ${proposal.added_lines} more lines of the ~${proposal.room} available, all from your profile. Review them, then Save & check and rebuild. Edited lines are marked with a dot; nothing is saved until you save, and Discard keeps the current version.`,
    },
  }
}

/** The Gaps step's state as the server has it (before any edits on this page). */
export function seedGaps(app: Application): NonNullable<StepMemo['gaps']> {
  return {
    answers: Object.fromEntries(app.answers.map((a) => [a.question_id, a])),
    proposals: [],
    guidance: app.meta.guidance ?? '',
  }
}

/** Evidence the AI drafted from gap answers, waiting for approval. `asked`: the questions it was drafted for
 *  (their older pending drafts are replaced); by default, the questions the new drafts answer. */
export function withProposals(m: StepMemo, app: Application, proposals: Proposal[], asked?: string[]): StepMemo {
  const g = m.gaps ?? seedGaps(app)
  const ids = new Set(asked ?? proposals.map((p) => p.question_id))
  return {
    ...m,
    gaps: {
      ...g,
      proposals: [
        ...g.proposals.filter((d) => !ids.has(d.question_id) || d.state === 'approved'),
        ...proposals.map((p): Draft => ({ ...p, state: 'pending', uid: `${p.question_id}-${Date.now()}-${Math.random().toString(36).slice(2)}` })),
      ],
    },
  }
}
