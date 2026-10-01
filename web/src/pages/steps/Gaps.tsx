import { useState } from 'react'
import { api, type Proposal } from '../../api'
import { cx, ErrorNote, Section, Spinner } from '../../ui'
import type { StepProps } from '../Workspace'

type Answer = { text: string; none: boolean }
type Draft = Proposal & { state: 'pending' | 'approved' | 'rejected'; id?: string }

export default function Gaps({ app, profile, setApp, reloadProfile, go, run }: StepProps) {
  const questions = app.analysis?.questions ?? []
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [drafting, setDrafting] = useState(false)
  const [guidance, setGuidance] = useState('')
  const [error, setError] = useState<string | null>(null)

  const roles = profile.profile.roles
  const categories = profile.profile.skills.map((s) => s.category)
  const answered = questions.filter((q) => answers[q.id]?.text.trim() && !answers[q.id]?.none)
  const pending = drafts.filter((d) => d.state === 'pending').length

  const setAnswer = (id: string, patch: Partial<Answer>) =>
    setAnswers((prev) => ({ ...prev, [id]: { ...(prev[id] ?? { text: '', none: false }), ...patch } }))

  async function draftEvidence() {
    setDrafting(true)
    setError(null)
    try {
      const proposals = await api.proposals(app.id, answered.map((q) => ({ question_id: q.id, question: q.question, answer: answers[q.id].text })))
      setDrafts(proposals.map((p) => ({ ...p, state: 'pending' })))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDrafting(false)
    }
  }

  async function approve(i: number) {
    const d = drafts[i]
    try {
      const q = questions.find((x) => x.id === d.question_id)
      const res = await api.addEvidence({
        target: d.target, text: d.text, skills: d.skills,
        note: q ? `Q: ${q.question} A: ${answers[q.id]?.text ?? ''}` : undefined,
      })
      setDrafts((prev) => prev.map((x, j) => (j === i ? { ...x, state: 'approved', id: res.id } : x)))
      await reloadProfile()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const patchDraft = (i: number, patch: Partial<Draft>) =>
    setDrafts((prev) => prev.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  const compose = () =>
    run('Composing your tailored resume', [
      'Choosing the headline and leading highlights…',
      'Reordering evidence by relevance to this role…',
      'Rephrasing in the job’s vocabulary — facts locked…',
      'Running the fact-check and repairing any issues…',
      'Almost there — final fact-check pass…',
    ], async () => {
      setApp(await api.compose(app.id, guidance))
      go('review')
    })

  return (
    <div className="space-y-10">
      <Section eyebrow="Gaps" title={questions.length ? 'A few questions before writing' : 'No gaps to ask about'}>
        <p className="mb-6 max-w-2xl text-muted">
          {questions.length
            ? 'These requirements have weak or no evidence in your profile. Answer only with real experience. Anything you leave blank or mark “No real experience” stays a gap. AutoCV won’t paper over it.'
            : 'Your profile has evidence for every must-have. You can go straight to composing.'}
        </p>
        <ol className="space-y-5">
          {questions.map((q, i) => {
            const ans = answers[q.id] ?? { text: '', none: false }
            return (
              <li key={q.id} className="sheet animate-rise rounded p-5" style={{ animationDelay: `${i * 60}ms` }}>
                <p className="text-[11px] uppercase tracking-wider text-muted">{q.requirement}</p>
                <p className="mt-1 font-serif text-xl text-ink">{q.question}</p>
                <textarea
                  className={cx('field mt-3 min-h-[84px]', ans.none && 'opacity-40')}
                  disabled={ans.none}
                  placeholder="Where, what you did, the scale. Plain facts are best."
                  value={ans.text}
                  onChange={(e) => setAnswer(q.id, { text: e.target.value })}
                />
                <label className="mt-2 inline-flex cursor-pointer items-center gap-2 text-sm text-muted">
                  <input type="checkbox" className="accent-rust" checked={ans.none} onChange={(e) => setAnswer(q.id, { none: e.target.checked })} />
                  No real experience. Keep it as a gap.
                </label>
              </li>
            )
          })}
        </ol>
        {questions.length > 0 && (
          <button className="btn mt-5" disabled={!answered.length || drafting} onClick={draftEvidence}>
            {drafting ? <><Spinner /> Drafting evidence…</> : `Draft evidence from ${answered.length} answer${answered.length === 1 ? '' : 's'}`}
          </button>
        )}
      </Section>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {drafts.length > 0 && (
        <Section eyebrow="Your approval" title="Proposed additions to your master profile">
          <p className="mb-4 max-w-2xl text-sm text-muted">
            Edit the wording until it’s exactly true, then approve. Only approved items are saved, tagged as coming from you.
          </p>
          <div className="space-y-4">
            {drafts.map((d, i) => (
              <div key={i} className={cx('sheet rounded p-5 transition', d.state === 'approved' && 'border-ok/50 bg-ok-soft/40', d.state === 'rejected' && 'opacity-50')}>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span className="text-muted">Belongs to</span>
                  <select className="field w-auto py-1" disabled={d.state !== 'pending'} value={d.target} onChange={(e) => patchDraft(i, { target: e.target.value })}>
                    {roles.map((r) => <option key={r.id} value={r.id}>{r.employer}</option>)}
                    <option value="general">General (not role-specific)</option>
                  </select>
                  {d.state === 'approved' && <span className="chip bg-ok-soft text-ok">saved as {d.id}</span>}
                </div>
                <textarea className="field mt-3 min-h-[64px] font-serif text-[16px]" disabled={d.state !== 'pending'} value={d.text} onChange={(e) => patchDraft(i, { text: e.target.value })} />
                {d.skills.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">Skills to add:</span>
                    {d.skills.map((s, j) => (
                      <span key={j} className="chip">
                        {s.item}
                        <select
                          className="bg-transparent text-faint"
                          disabled={d.state !== 'pending'}
                          value={s.category}
                          onChange={(e) => patchDraft(i, { skills: d.skills.map((x, k) => (k === j ? { ...x, category: e.target.value } : x)) })}
                        >
                          {categories.map((c) => <option key={c}>{c}</option>)}
                        </select>
                        {d.state === 'pending' && (
                          <button onClick={() => patchDraft(i, { skills: d.skills.filter((_, k) => k !== j) })} aria-label={`Drop skill ${s.item}`}>×</button>
                        )}
                      </span>
                    ))}
                  </div>
                )}
                {d.state === 'pending' && (
                  <div className="mt-4 flex gap-2">
                    <button className="btn btn-primary" disabled={!d.text.trim()} onClick={() => approve(i)}>Approve & save</button>
                    <button className="btn" onClick={() => patchDraft(i, { state: 'rejected' })}>Reject</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section eyebrow="Compose" title="Write the tailored resume">
        <label className="block text-sm text-muted" htmlFor="guidance">Optional guidance, e.g. “lead with the mobile money fraud work” or “keep it hands-on”.</label>
        <textarea id="guidance" className="field mt-2 min-h-[64px]" value={guidance} onChange={(e) => setGuidance(e.target.value)} />
        <div className="mt-5 flex items-center gap-4">
          <button className="btn btn-primary" onClick={compose} disabled={pending > 0}>
            {app.tailored ? 'Re-compose tailored resume →' : 'Compose tailored resume →'}
          </button>
          {pending > 0 && <span className="text-sm text-warn">Approve or reject the {pending} pending proposal{pending > 1 ? 's' : ''} first.</span>}
          {app.tailored && <button className="btn btn-ghost" onClick={() => go('review')}>Back to the current draft</button>}
        </div>
      </Section>
    </div>
  )
}
