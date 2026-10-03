---
name: profile
description: Build or enrich the user's master profile (<data folder>/profile.yaml) — ingest the base resume, mine the interview prep guide for verified facts, run an enrichment interview, and approve headlines/synonyms. Use for first-time setup or when the user has new achievements, skills, or documents to add.
argument-hint: "[ingest | prep-guide <path> | interview [role] | headlines]"
---

# /profile — curate the source of truth

The rules in `CLAUDE.md` apply. Every change to `<data folder>/profile.yaml` needs the user's explicit approval of the exact wording. Work in small batches and validate after each edit with `uv run autocv evidence`, which fails loudly on a schema error.

## ingest (first run only)
1. Make sure the base resume is at `<data folder>/source/base_resume.docx`.
2. `uv run autocv ingest`, then `uv run autocv baseline`. The text must be identical. (The web UI's Welcome page imports any resume layout through the AI; `ingest` reads AutoCV's own layout.)
3. Walk the user through what was captured: roles, achievement ids, skills.

## prep-guide <path>
1. Copy the guide into `<data folder>/source/`. If it's .docx, read it with `pandoc -t markdown`; for PDF use the Read tool.
2. Extract **candidate evidence**: achievements, metrics, tools, scope, and outcomes that are stated in the guide but missing from (or richer than) the profile. Write them to `<data folder>/profile_candidates.yaml`:
   ```yaml
   - role: acme-corp               # or summary / project / skill
     text: proposed evidence sentence
     quote: "exact passage from the guide"
     why: what it adds (new metric / tool / story)
   ```
   Skip anything hypothetical ("I would…"), aspirational, or vague. Flag conflicts with existing profile numbers rather than resolving them.
3. Review with the user in batches of 4 or fewer using AskUserQuestion, with options Approve / Edit / Reject.
   - Approved items go into the profile with `source: prep_guide`, `in_base_resume: false`, the next free id (e.g. `acme-corp.a7`), and `note:` holding the quote.
   - New skills go into the matching `skills` group, but only if the user confirms hands-on use.
4. Save the STAR stories and Q&A to `private/stories.yaml` as `{id, question, situation, task, action, result, evidence_ids}`, for future interview prep. They are never used as resume claims unless they're also approved evidence.

## interview [role]
For when the user isn't sure what's missing. Go role by role, newest first, asking 4 or fewer questions per batch (AskUserQuestion with a "Skip" option). Target what job descriptions in the user's field (Settings → Your targets) commonly ask for that the profile doesn't show. For example, for a senior cybersecurity profile:
- **Scale:** number of assets or properties, traffic, alerts or incidents per month, users protected, regions.
- **Outcomes:** MTTD/MTTR changes, audit or regulatory results, cost saved, programs delivered, adoption.
- **Hands-on technology:** cloud (AWS/Azure/GCP), IAM, containers/K8s, SIEM/SOAR, EDR, CSPM, IaC, languages, AI/LLM security.
- **Leadership:** team sizes over time, hiring, budget, stakeholders, board/regulator exposure, cross-region scope.
- **Domains:** zero trust, cloud security, AppSec/DevSecOps, red/purple team, GRC, third-party risk, OT, crypto/digital assets.
- **Certifications** held or in progress (with dates), plus publications, talks, patents and open-source work.

Turn each confirmed answer into one evidence sentence and show the exact wording. Save it only after the user approves (`source: interview`). "Exposure" or "learning" answers aren't evidence; record nothing.

## headlines
Draft 2–3 additional headline options (for example, an individual-contributor version alongside a manager one). Each must only use claims supported by the profile. the user approves the wording and the `tracks`, and only then is it added to `headlines`. Do the same for `synonyms` (e.g. `[CRM, Customer Relationship Management]`) and any `vocabulary` terms.
