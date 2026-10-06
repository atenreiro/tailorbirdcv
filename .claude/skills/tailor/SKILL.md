---
name: tailor
description: Tailor the user's resume to a job description (pasted text, file path, or URL) — analyse the JD, ask about gaps, compose a fact-locked tailored resume, fact-check it, and build the .docx/.pdf. Use when the user shares a JD or asks to customise the resume for a role.
argument-hint: <JD text | file path | URL>
---

# /tailor — one application

Read `CLAUDE.md` rules first. The master profile `<data folder>/profile.yaml` is the only source of facts. If it does not exist, stop and run `/profile` first.

## 1. Intake
- JD from `$ARGUMENTS`: pasted text, a file path, or a URL (fetch with WebFetch; if the page is blocked or truncated, ask the user to paste it).
- Identify company and role title, then `uv run tailorbirdcv new "<Company>" "<Role>"`. Save the full JD verbatim to `<app>/jd.md`.

## 2. Analyse → `<app>/analysis.yaml`
```yaml
company: ...
role: ...
industry: <a lens key>     # the keys of the active industries config: <data folder>/config/industries.yaml if present, else the pack's, else tailorbirdcv/data/config/industries.yaml
track: manager | ic | hybrid   # tracks.yaml, resolved the same way
seniority: ...
location: ...
requirements:            # each JD requirement, in JD order
  - text: ...
    priority: must | nice
    status: strong | partial | gap
    evidence: [profile ids]
keywords:                # 15–30 ATS terms as the JD writes them
  - {term: detection engineering, priority: must, aliases: [detection logic]}
```
Show the user a short summary: role, industry lens, track, top 5 must-haves with status, and the gaps. If the industry or track is ambiguous (e.g. a "Team Lead" role at a quant firm), ask.

## 2b. Use what TailorbirdCV remembers (`private/knowledge.yaml`)
- `answers` with `kind: no_experience` on the same topic are **known gaps**. Don't ask again; tell the user "known gap (you said no on <date>)" and offer to revisit if it changed.
- A related past answer → ask, but quote it so he can confirm or update rather than retype.
- `preferences` with `status: active` are approved style rules. Apply them when composing. They never override the fact rules.
- Knowledge is **not evidence**. Only `<data folder>/profile.yaml` can be cited.

## 3. Ask about gaps (AskUserQuestion, ≤4 per batch)
For each `gap` or weak `partial` on a must-have, ask a concrete question, e.g. "The JD asks for Kubernetes/container security. Have you done real work on this? If so, where and what?" Include an option for "No real experience".
- If the user confirms new evidence, draft the exact wording and get their OK. Then add it to the profile under the right role (`source: interview`, `in_base_resume: false`, next free id) and re-validate with `uv run tailorbirdcv evidence`.
- No experience → it stays a gap. Do **not** soften it into "exposure to" or "familiar with".
- Record each final answer in `private/knowledge.yaml` → `answers`, with fields `id` (k<n>), `topic`, `question`, `answer`, `kind` (experience | no_experience), `evidence_id` (if approved), `app_id`, `company`, `date`. The web UI reads the same file.

## 4. Compose `<app>/tailored.yaml`
The schema is in `tailorbirdcv/schema.py`; `<data folder>/source/base_tailored.yaml` is a complete example.
- `headline`: an approved headline id whose `tracks` include the JD's track. If none fits well, propose new wording to the user. It enters the profile only once they approve it.
- `summary`: 2–3 sentences, rewritten for the JD, citing every evidence id used.
- `highlights`: 3–5, most JD-relevant first, each citing sources.
- `competencies`: reorder groups and items so the JD's priorities come first. Items must be profile skills, approved synonyms, or sub-phrases of one skill. Group labels may change.
- `experience`: keep every role, in reverse-chronological order. Per role:
  - Reorder bullets by JD relevance and rephrase using the JD's vocabulary where the meaning is identical.
  - Merge or drop low-relevance bullets.
  - You may surface profile evidence with `in_base_resume: false`.
  - Older roles get fewer bullets.
- Each claim's `sources` must contain everything it relies on (numbers, tools, names). Citing a role-bound id also allows that role's employer and title.
- Apply the active industry lens (`lead_with`, `mirror_terms`, tone) and track rules (ordering, bullet style) as emphasis only.

## 5. Gate
`uv run tailorbirdcv check <app>` must PASS. To fix an error:
- cite the right evidence, or
- reword to match the source, or
- remove the claim.

Never fix an error by editing the profile, vocabulary or synonyms without the user's approval. Then use the ATS lines: add `unused` keywords where the evidence genuinely supports them, and leave `gap` keywords alone.

Before building, self-review: compare each changed bullet with its sources for verb or scope inflation ("supported" → "led", team → organization). Fix anything that overstates.

## 6. Build
`uv run tailorbirdcv build <app>`. Exit code 2 means over the page limit (Settings → Your targets): trim the lowest-relevance bullets (oldest roles first), check, and rebuild. A PDF engine (Word or LibreOffice) must be installed; `uv run tailorbirdcv doctor` checks.

## 7. Hand-off (chat only, no extra files)
- The .docx and .pdf paths.
- Headline, industry and track chosen.
- The 3–5 most significant changes.
- Must-have keyword coverage.
- A compact **claim → source** table for the most heavily rephrased bullets, so the user can verify.
- Remaining gaps, worth addressing in a cover note or interview.
- A reminder to read it once before sending.
