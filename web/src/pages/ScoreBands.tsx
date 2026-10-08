import type { CritiqueResult, ScoreKey } from '../api'
import { cx } from '../lib'

/** The hiring-manager review scores 1–10, but they're the AI's judgement: the same draft can move a point between
 *  runs, and nearly everything lands on 5–7. So they're shown as four bands, each with the AI's reason; the number
 *  stays underneath (tooltip, screen readers) and a change is shown only when it crosses a band. */
const BANDS = [
  { min: 9, label: 'Strong', dots: 4, cls: 'text-ok' },
  { min: 7, label: 'Good', dots: 3, cls: 'text-ok' },
  { min: 5, label: 'Fair', dots: 2, cls: 'text-warn' },
  { min: 1, label: 'Weak', dots: 1, cls: 'text-bad' },
] as const

const band = (score: number) => BANDS.find((b) => score >= b.min) ?? BANDS[BANDS.length - 1]

const SCORE_LABEL: Record<ScoreKey, string> = { fit: 'Fit to must-haves', impact: 'Impact', clarity: 'Clarity', seniority: 'Seniority signal' }
const KEYS = Object.keys(SCORE_LABEL) as ScoreKey[]

function Meter({ score }: { score: number }) {
  const b = band(score)
  return (
    <span aria-hidden className={cx('inline-flex items-center gap-[3px]', b.cls)}>
      {[0, 1, 2, 3].map((i) => <span key={i} className={cx('size-[7px] rounded-full', i < b.dots ? 'bg-current' : 'bg-line')} />)}
    </span>
  )
}

/** The four scores as bands with their reasons. `previous`: the run before, for "up from Fair". */
export function ScoreBands({ scores, previous, className }: { scores: CritiqueResult['scores']; previous?: CritiqueResult['scores'] | null; className?: string }) {
  return (
    <dl className={cx('grid gap-3', className)}>
      {KEYS.map((k) => {
        const { score, why } = scores[k]
        const b = band(score), before = previous?.[k] ? band(previous[k].score) : null
        const moved = before && before.label !== b.label ? (before.min < b.min ? 'up' : 'down') : null
        return (
          <div key={k} className="min-w-0">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-muted">{SCORE_LABEL[k]}</dt>
              <dd className="flex flex-none items-center gap-2" title={`${score}/10`}>
                <span className={cx('text-[13px] font-semibold', b.cls)}>{b.label}<span className="sr-only"> ({score} out of 10)</span></span>
                <Meter score={score} />
              </dd>
            </div>
            <p className="mt-0.5 text-xs leading-[1.45] text-body text-pretty">
              {moved && <span className={cx('mr-1.5 font-mono text-[10px]', moved === 'up' ? 'text-ok' : 'text-bad')}>{moved === 'up' ? '↑' : '↓'} from {before!.label}</span>}
              {why}
            </p>
          </div>
        )
      })}
    </dl>
  )
}
