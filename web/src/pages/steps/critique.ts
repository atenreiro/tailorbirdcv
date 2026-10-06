// Mirrors tailorbirdcv/critique.py apply_issue: targets are found by their ORIGINAL text, so
// accepting one fix never misapplies another after indices shift.
import type { Claim, Critique, CritiqueIssue, Tailored } from '../../api'

const norm = (s: string) => s.split(/\s+/).join(' ').trim()
const same = (c: Claim | null | undefined, original?: Claim) => !!c && !!original && norm(c.text) === norm(original.text)

export function findsTarget(t: Tailored, issue: CritiqueIssue): boolean {
  try {
    applyIssue(structuredClone(t), issue)
    return true
  } catch {
    return false
  }
}

/** Applies the issue to `t` in place. Throws if the target line changed since the review. */
export function applyIssue(t: Tailored, issue: CritiqueIssue): void {
  if (issue.action === 'advice') return
  const changed = () => { throw new Error('That line has changed since the review. Re-run the review.') }
  const { where, original } = issue
  if (where === 'summary') {
    if (!same(t.summary, original)) changed()
    if (issue.action === 'rewrite') t.summary = { ...issue.rewrite! }
    else if (issue.action === 'remove') t.summary = null
    return
  }
  if (/^experience\[\d+\]\.scope$/.test(where)) {
    const role = t.experience.find((r) => same(r.scope, original))
    if (!role) changed()
    if (issue.action === 'rewrite') role!.scope = { ...issue.rewrite! }
    else if (issue.action === 'remove') role!.scope = null
    return
  }
  const lists = where.startsWith('highlights[') ? [t.highlights] : t.experience.map((r) => r.bullets)
  for (const list of lists) {
    const i = list.findIndex((c) => same(c, original))
    if (i < 0) continue
    if (issue.action === 'rewrite') list[i] = { ...issue.rewrite! }
    else if (issue.action === 'remove') list.splice(i, 1)
    else if (issue.action === 'move_to_top') list.unshift(list.splice(i, 1)[0])
    return
  }
  changed()
}

/** Is this issue about this exact claim (as it currently reads)? */
export function issueTargets(issue: CritiqueIssue, claim: Claim): boolean {
  return issue.action !== undefined && same(claim, issue.original)
}

/** Review suggestions the user hasn't accepted or rejected yet. */
export function openIssues(c: Critique | null): CritiqueIssue[] {
  return c ? c.latest.issues.filter((i) => !c.decisions[i.id]) : []
}
