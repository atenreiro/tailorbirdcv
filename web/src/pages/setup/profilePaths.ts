// Paths into an imported profile, as the server's import check reports them:
//   contact.name|location|phone|email · contact.links[i].text|url · headlines[i]
//   skills[g].category · skills[g].items[j] · <roleId>.employer|location|title|dates
//   <evidence id> (summary, highlights, scope, achievements) · <lead item id> (sub-roles, projects, education, extras)
// During review nothing is spliced out (indices would shift under the flagged paths): removals are
// collected by "removal key" and applied when saving, with the confirmed paths renumbered to match.
import type { Profile } from '../../api'

export type Lead = { label: string; text: string }
export type Value = string | Lead

const CONTACT = /^contact\.(name|location|phone|email)$/
const LINK = /^contact\.links\[(\d+)\]\.(text|url)$/
const HEADLINE = /^headlines\[(\d+)\]$/
const SKILL_CAT = /^skills\[(\d+)\]\.category$/
const SKILL_ITEM = /^skills\[(\d+)\]\.items\[(\d+)\]$/
const ROLE_FIELD = /^(.+)\.(employer|location|title|dates)$/

type Located =
  | { kind: 'contact'; key: 'name' | 'location' | 'phone' | 'email' }
  | { kind: 'link'; i: number; part: 'text' | 'url' }
  | { kind: 'headline'; i: number }
  | { kind: 'skill-cat'; g: number }
  | { kind: 'skill-item'; g: number; j: number }
  | { kind: 'role'; r: number; field: 'employer' | 'location' | 'title' | 'dates' }
  | { kind: 'evidence'; get: (p: Profile) => { text: string } }
  | { kind: 'lead'; get: (p: Profile) => Lead }

function locate(p: Profile, path: string): Located | null {
  let m
  if ((m = path.match(CONTACT))) return { kind: 'contact', key: m[1] as 'name' }
  if ((m = path.match(LINK))) return { kind: 'link', i: +m[1], part: m[2] as 'text' }
  if ((m = path.match(HEADLINE))) return { kind: 'headline', i: +m[1] }
  if ((m = path.match(SKILL_CAT))) return { kind: 'skill-cat', g: +m[1] }
  if ((m = path.match(SKILL_ITEM))) return { kind: 'skill-item', g: +m[1], j: +m[2] }
  if ((m = path.match(ROLE_FIELD))) {
    const r = p.roles.findIndex((x) => x.id === m![1])
    if (r >= 0) return { kind: 'role', r, field: m[2] as 'title' }
  }
  for (const key of ['summary_facts', 'highlights'] as const) {
    const i = p[key].findIndex((e) => e.id === path)
    if (i >= 0) return { kind: 'evidence', get: (q) => q[key][i] }
  }
  for (let r = 0; r < p.roles.length; r++) {
    const role = p.roles[r]
    if (role.scope?.id === path) return { kind: 'evidence', get: (q) => q.roles[r].scope! }
    const a = role.achievements.findIndex((e) => e.id === path)
    if (a >= 0) return { kind: 'evidence', get: (q) => q.roles[r].achievements[a] }
    const s = role.sub_roles.findIndex((e) => e.id === path)
    if (s >= 0) return { kind: 'lead', get: (q) => q.roles[r].sub_roles[s] }
  }
  for (const key of ['projects', 'education', 'extras'] as const) {
    const i = p[key].findIndex((e) => e.id === path)
    if (i >= 0) return { kind: 'lead', get: (q) => q[key][i] }
  }
  return null
}

export function getValue(p: Profile, path: string): Value | null {
  const at = locate(p, path)
  if (!at) return null
  switch (at.kind) {
    case 'contact': return p.contact[at.key] ?? ''
    case 'link': return p.contact.links[at.i]?.[at.part] ?? ''
    case 'headline': return p.headlines[at.i]?.text ?? ''
    case 'skill-cat': return p.skills[at.g]?.category ?? ''
    case 'skill-item': return p.skills[at.g]?.items[at.j] ?? ''
    case 'role': return p.roles[at.r][at.field]
    case 'evidence': return at.get(p).text
    case 'lead': { const l = at.get(p); return { label: l.label, text: l.text } }
  }
}

export function setValue(p: Profile, path: string, value: Value): Profile {
  const q = structuredClone(p)
  const at = locate(q, path)
  if (!at) return p
  const str = typeof value === 'string' ? value.trim() : ''
  switch (at.kind) {
    case 'contact': q.contact[at.key] = str; break
    case 'link': q.contact.links[at.i][at.part] = str; break
    case 'headline': q.headlines[at.i].text = str; break
    case 'skill-cat': q.skills[at.g].category = str; break
    case 'skill-item': q.skills[at.g].items[at.j] = str; break
    case 'role': q.roles[at.r][at.field] = str; break
    case 'evidence': at.get(q).text = str; break
    case 'lead': { const l = at.get(q); const v = value as Lead; l.label = v.label.trim(); l.text = v.text.trim() }
  }
  return q
}

/** The key that removes the line at `path` (a whole link, skill item, headline or evidence item),
 *  or null when it can only be fixed or confirmed (name, employer, title, dates, skill categories). */
export function removalKey(p: Profile, path: string): string | null {
  const at = locate(p, path)
  if (!at) return null
  switch (at.kind) {
    case 'contact': return at.key === 'name' ? null : path
    case 'link': return `contact.links[${at.i}]`
    case 'headline': return p.headlines.length > 1 ? path : null
    case 'skill-item': return path
    case 'evidence': case 'lead': return path
    default: return null
  }
}

/** The profile as it will be saved: removals applied. */
export function applyRemovals(p: Profile, removed: Set<string>): Profile {
  const q = structuredClone(p)
  if (removed.has('contact.location')) q.contact.location = ''
  for (const key of ['phone', 'email'] as const) if (removed.has(`contact.${key}`)) delete q.contact[key]
  q.contact.links = q.contact.links.filter((_, i) => !removed.has(`contact.links[${i}]`))
  q.headlines = q.headlines.filter((_, i) => !removed.has(`headlines[${i}]`))
  q.skills = q.skills.map((g, gi) => ({ ...g, items: g.items.filter((_, j) => !removed.has(`skills[${gi}].items[${j}]`)) }))
    .filter((g) => g.items.length > 0)
  q.summary_facts = q.summary_facts.filter((e) => !removed.has(e.id))
  q.highlights = q.highlights.filter((e) => !removed.has(e.id))
  q.roles = q.roles.map((r) => ({
    ...r, scope: r.scope && removed.has(r.scope.id) ? undefined : r.scope,
    achievements: r.achievements.filter((e) => !removed.has(e.id)),
    sub_roles: r.sub_roles.filter((e) => !removed.has(e.id)),
  }))
  for (const key of ['projects', 'education', 'extras'] as const) q[key] = q[key].filter((e) => !removed.has(e.id))
  return q
}

/** A path renumbered for the saved profile (earlier siblings removed shift indices down). */
export function finalPath(p: Profile, path: string, removed: Set<string>): string {
  const before = (n: number, key: (k: number) => string) => Array.from({ length: n }, (_, k) => key(k)).filter((k) => removed.has(k)).length
  let m
  if ((m = path.match(LINK))) return `contact.links[${+m[1] - before(+m[1], (k) => `contact.links[${k}]`)}].${m[2]}`
  if ((m = path.match(HEADLINE))) return `headlines[${+m[1] - before(+m[1], (k) => `headlines[${k}]`)}]`
  // a skill group whose items were all removed disappears, shifting the groups after it
  const groupGone = (k: number) => p.skills[k].items.every((_, j) => removed.has(`skills[${k}].items[${j}]`))
  const groupShift = (g: number) => p.skills.slice(0, g).filter((_, k) => groupGone(k)).length
  if ((m = path.match(SKILL_CAT))) return `skills[${+m[1] - groupShift(+m[1])}].category`
  if ((m = path.match(SKILL_ITEM))) {
    const g = +m[1], j = +m[2]
    return `skills[${g - groupShift(g)}].items[${j - before(j, (k) => `skills[${g}].items[${k}]`)}]`
  }
  return path
}
