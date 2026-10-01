import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { cx, Section } from '../../ui'
import type { StepProps } from '../Workspace'
import Cite from './Cite'

const STATUS_DOT = { strong: 'bg-ok', partial: 'bg-warn', gap: 'bg-bad' }
const STATUS_LABEL = { strong: 'Strong', partial: 'Partial', gap: 'Gap' }

export default function Brief({ app, profile, setApp, go, run }: StepProps) {
  const nav = useNavigate()
  const [showJd, setShowJd] = useState(!app.analysis)
  const a = app.analysis

  const analyze = () =>
    run('Reading the job description', [
      'Identifying the industry lens and track…',
      'Matching every requirement to your evidence…',
      'Picking out ATS keywords…',
      'Drafting questions about gaps…',
    ], async () => {
      const next = await api.analyze(app.id)
      setApp(next)
      if (next.id !== app.id) nav(`/a/${next.id}`, { replace: true })
    })

  return (
    <div className="space-y-10">
      {!a && (
        <div className="sheet animate-rise rounded px-8 py-10 text-center">
          <p className="font-serif text-2xl text-ink">Not analyzed yet.</p>
          <p className="mt-1 text-muted">AutoCV will work out the industry, the IC vs manager track, and how your evidence stacks up against each requirement.</p>
          <button className="btn btn-primary mt-5" onClick={analyze}>Analyze the role</button>
        </div>
      )}

      {a && (
        <>
          <div className="grid gap-6 md:grid-cols-[1.4fr_1fr]">
            <Section eyebrow="The brief">
              <p className="font-serif text-2xl leading-snug text-ink">{a.summary}</p>
            </Section>
            <dl className="animate-rise grid grid-cols-2 gap-px self-start overflow-hidden rounded border border-rule bg-rule text-sm">
              {[['Industry lens', a.industry], ['Track', a.track], ['Seniority', a.seniority], ['Location', a.location]].map(([k, v]) => (
                <div key={k} className="bg-sheet px-4 py-3">
                  <dt className="text-[11px] uppercase tracking-wider text-muted">{k}</dt>
                  <dd className="mt-0.5 font-medium capitalize text-ink">{v || '—'}</dd>
                </div>
              ))}
            </dl>
          </div>

          <Section
            eyebrow="Requirements"
            title="How your evidence stacks up"
            aside={
              <div className="flex gap-4 text-xs text-muted">
                {(['strong', 'partial', 'gap'] as const).map((s) => (
                  <span key={s} className="flex items-center gap-1.5">
                    <span className={cx('size-2 rounded-full', STATUS_DOT[s])} />
                    {a.requirements.filter((r) => r.status === s).length} {STATUS_LABEL[s].toLowerCase()}
                  </span>
                ))}
              </div>
            }
          >
            <ul className="divide-y divide-rule/70">
              {a.requirements.map((r, i) => (
                <li key={i} className="grid gap-2 py-3 md:grid-cols-[90px_1fr_1fr]">
                  <span className="flex items-center gap-2 text-xs">
                    <span className={cx('size-2 rounded-full', STATUS_DOT[r.status])} />
                    <span className="font-medium text-ink">{STATUS_LABEL[r.status]}</span>
                  </span>
                  <span>
                    <span className="text-ink">{r.text}</span>
                    {r.priority === 'must' && <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-rust">must</span>}
                    {r.note && <span className="block text-xs text-muted">{r.note}</span>}
                  </span>
                  <span className="flex flex-wrap content-start gap-1">
                    {r.evidence.map((e) => <Cite key={e} id={e} text={profile.evidence[e]} />)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          <Section eyebrow="ATS keywords" title="The vocabulary to mirror">
            <div className="flex flex-wrap gap-2">
              {a.keywords.map((k) => (
                <span
                  key={k.term}
                  title={k.aliases.length ? `also: ${k.aliases.join(', ')}` : undefined}
                  className={cx('rounded-full border px-3 py-1 text-sm', k.priority === 'must' ? 'border-rust/40 bg-rust-soft text-rust' : 'border-rule bg-sheet text-body')}
                >
                  {k.term}
                </span>
              ))}
            </div>
          </Section>
        </>
      )}

      <Section
        eyebrow="Source"
        title="Job description"
        aside={<button className="btn btn-ghost text-sm" onClick={() => setShowJd((s) => !s)}>{showJd ? 'Hide' : 'Show'}</button>}
      >
        {showJd && <pre className="sheet max-h-[480px] overflow-auto whitespace-pre-wrap rounded px-6 py-5 font-serif text-[15px] leading-relaxed text-body">{app.jd}</pre>}
      </Section>

      {a && (
        <div className="flex items-center justify-between border-t border-rule pt-6">
          <button className="btn" onClick={analyze}>Re-analyze</button>
          <button className="btn btn-primary" onClick={() => go('gaps')}>
            {a.questions.length ? `Answer ${a.questions.length} gap question${a.questions.length > 1 ? 's' : ''} →` : 'Continue →'}
          </button>
        </div>
      )}
    </div>
  )
}
