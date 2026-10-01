import type { Critique, CritiqueIssue, ScoreKey } from '../../api'
import { cx } from '../../ui'

const KIND_LABEL: Record<string, string> = {
  buried_must_have: 'Buried must-have', weak_opening: 'Weak opening', duty_not_outcome: 'Duty, not outcome',
  redundant: 'Redundant', jargon: 'Jargon', too_long: 'Too long', unused_evidence: 'Stronger evidence unused',
  unclear: 'Unclear', seniority_signal: 'Seniority signal', ordering: 'Ordering',
}
const ACTION_LABEL: Record<string, string> = { remove: 'Remove this line', move_to_top: 'Move this line to the top' }
const SEV = { high: 'bg-bad-soft text-bad', medium: 'bg-warn-soft text-warn', low: 'bg-wash text-muted' }
const VERDICT = {
  interview: { label: 'Would interview', cls: 'border-ok text-ok' },
  borderline: { label: 'Borderline', cls: 'border-warn text-warn' },
  pass: { label: 'Would pass', cls: 'border-bad text-bad' },
}
const SCORE_LABEL: Record<ScoreKey, string> = { fit: 'Fit to must-haves', impact: 'Impact', clarity: 'Clarity', seniority: 'Seniority signal' }

export interface ReviewActions {
  decide: (issue: CritiqueIssue, decision: 'accepted' | 'rejected') => void
  answer: (issue: CritiqueIssue) => void
}

/** One review issue, shown inline under its claim or in the card. */
export function ReviewIssue({ issue, actions, compact = false }: { issue: CritiqueIssue; actions: ReviewActions; compact?: boolean }) {
  const editable = issue.action !== 'advice'
  return (
    <div className={cx('rounded border border-rust/25 bg-rust-soft/40 p-3 text-xs', !compact && 'mt-2')}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold uppercase tracking-wider text-rust">Hiring manager</span>
        <span className={cx('rounded-full px-2 py-0.5 text-[10px] font-semibold', SEV[issue.severity])}>{KIND_LABEL[issue.kind] ?? issue.kind}</span>
        {issue.note_for && <span className="chip">note for {issue.note_for === 'cover_letter' ? 'cover letter' : 'interview'}</span>}
      </div>
      <p className="mt-1.5 text-body">{issue.problem}</p>
      {issue.action === 'rewrite' && issue.rewrite && (
        <div className="mt-2 rounded bg-sheet p-2">
          <p className="text-[10px] uppercase tracking-wider text-faint">Suggested · fact-checked</p>
          <p className="mt-0.5 font-serif text-[14px] leading-snug text-ink">{issue.rewrite.text}</p>
        </div>
      )}
      {(issue.action === 'remove' || issue.action === 'move_to_top') && (
        <p className="mt-2 font-medium text-ink">→ {ACTION_LABEL[issue.action]}</p>
      )}
      {issue.blocked && <p className="mt-2 text-faint">The AI’s rewrite was withheld: it didn’t pass the fact-check.</p>}
      {issue.question && (
        <p className="mt-2 text-ink">Needs your input: <span className="italic">{issue.question}</span></p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {editable && <button className="btn btn-primary px-3 py-1 text-xs" onClick={() => actions.decide(issue, 'accepted')}>Accept</button>}
        {issue.question && <button className="btn px-3 py-1 text-xs" onClick={() => actions.answer(issue)}>Answer in Gaps</button>}
        <button className="btn px-3 py-1 text-xs" onClick={() => actions.decide(issue, 'rejected')}>{editable ? 'Reject' : 'Dismiss'}</button>
      </div>
    </div>
  )
}

export function openIssues(c: Critique | null): CritiqueIssue[] {
  return c ? c.latest.issues.filter((i) => !c.decisions[i.id]) : []
}

export function HiringManagerCard({ critique, canRun, dirty, onRun, onAcceptAll, actions, isInline }: {
  critique: Critique | null; canRun: boolean; dirty: boolean
  onRun: () => void; onAcceptAll: () => void; actions: ReviewActions
  isInline: (issue: CritiqueIssue) => boolean
}) {
  const open = openIssues(critique)
  const general = open.filter((i) => !isInline(i))
  const acceptable = open.filter((i) => i.action !== 'advice').length
  const r = critique?.latest
  return (
    <div className="sheet animate-rise rounded p-5" style={{ animationDelay: '110ms' }}>
      <div className="flex items-center justify-between">
        <p className="eyebrow">Hiring-manager review</p>
        {r && <span className={cx('rounded-sm border-2 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em]', VERDICT[r.verdict.decision].cls)}>{VERDICT[r.verdict.decision].label}</span>}
      </div>
      {!r && <p className="mt-2 text-sm text-muted">Read this draft as the role’s hiring manager and a recruiter skimming the top third would. Takes about 1–1.5 minutes. Every suggested fix is fact-checked before you see it.</p>}
      {r && (
        <>
          {critique!.stale && <p className="mt-2 rounded bg-warn-soft px-2 py-1 text-xs text-warn">The draft changed since this review. Re-run it for fresh scores.</p>}
          <p className="mt-2 text-sm text-body">{r.verdict.reason}</p>
          <dl className="mt-3 space-y-1.5">
            {(Object.keys(SCORE_LABEL) as ScoreKey[]).map((k) => {
              const prev = critique!.previous_scores?.[k]?.score
              const delta = prev === undefined ? 0 : r.scores[k].score - prev
              return (
                <div key={k} title={r.scores[k].why}>
                  <div className="flex justify-between text-xs text-muted">
                    <dt>{SCORE_LABEL[k]}</dt>
                    <dd className="font-mono">
                      {r.scores[k].score}/10
                      {delta !== 0 && <span className={delta > 0 ? 'ml-1 text-ok' : 'ml-1 text-bad'}>{delta > 0 ? `+${delta}` : delta}</span>}
                    </dd>
                  </div>
                  <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-wash">
                    <div className="h-full rounded-full bg-rust" style={{ width: `${r.scores[k].score * 10}%` }} />
                  </div>
                </div>
              )
            })}
          </dl>
          <div className="mt-4 border-t border-rule pt-3 text-xs">
            <p className="font-semibold uppercase tracking-wider text-muted">Recruiter’s 6-second skim</p>
            <p className="mt-1 text-body">{r.skim.takeaway}</p>
            {r.skim.lands.map((x, i) => <p key={`l${i}`} className="text-ok">+ {x}</p>)}
            {r.skim.misses.map((x, i) => <p key={`m${i}`} className="text-bad">− {x}</p>)}
          </div>
          {r.strengths.length > 0 && (
            <div className="mt-3 border-t border-rule pt-3 text-xs">
              <p className="font-semibold uppercase tracking-wider text-muted">Keep</p>
              {r.strengths.map((s, i) => <p key={i} className="text-body">✓ {s.why}</p>)}
            </div>
          )}
          <p className="mt-3 border-t border-rule pt-3 text-xs text-muted">
            {open.length ? `${open.length} open suggestion${open.length > 1 ? 's' : ''}. Line-specific ones are shown under each line.` : 'All suggestions handled.'}
          </p>
          {general.length > 0 && <div className="mt-2 space-y-2">{general.map((i) => <ReviewIssue key={i.id} issue={i} actions={actions} compact />)}</div>}
        </>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn flex-1 justify-center" disabled={!canRun} onClick={onRun}
          title={dirty ? 'Save your edits first' : canRun ? '' : 'Fix the fact-check errors first'}>
          {r ? 'Re-run review' : 'Run review'}
        </button>
        {acceptable > 1 && <button className="btn btn-primary" onClick={onAcceptAll}>Accept all {acceptable}</button>}
      </div>
    </div>
  )
}
