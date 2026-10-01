# AutoCV

Tailors the user's resume to a job description without inventing anything. Senior cybersecurity roles (IC or manager) across banking, tech, quant, fintech, telco; Singapore/APAC; max 2 pages; US spelling.

## Non-negotiable rules
1. **Never invent.** Every claim in a tailored resume must trace to `private/profile.yaml`. No new numbers, tools, employers, scope, outcomes, or implied experience — not even "familiar with". If the JD wants something the profile lacks, **ask the user**; if he has no real experience, it stays a gap.
2. **Locked fields never change**: contact, employer, location, job title, dates, education, certifications, awards, languages. The renderer pulls them from the profile by id — never retype them.
3. **The profile changes only with the user's explicit confirmation of the exact wording.** New evidence gets `source: interview` or `source: prep_guide` and `in_base_resume: false`.
4. **Rephrasing is allowed** (reorder, merge, trim, mirror JD vocabulary) as long as the meaning, numbers and entities are unchanged and each claim cites its `sources`. Don't upgrade verbs ("contributed to" → "led") or scope ("team" → "organization").
5. `uv run autocv check` must PASS before `build`. Fix violations by citing the right evidence or rewording; never by adding vocabulary or synonyms without the user's approval.
6. Personal data lives only in `private/` (gitignored). Never commit it, never paste it into tests — tests use `tests/fixtures/` (fictional).

## Layout
- `autocv/` — `schema.py` (models), `ingest.py` (docx → profile), `render.py` (pixel-faithful docx), `factcheck.py` (blocking gate), `ats.py` (keyword coverage), `pdf.py` (Word → PDF), `cli.py`.
- `config/industries.yaml`, `config/tracks.yaml` — emphasis heuristics only, never facts.
- `templates/base.docx` — theme/page setup with empty body, no PII.
- `.claude/skills/profile` (`/profile`) and `.claude/skills/tailor` (`/tailor`).
- `private/` — `profile.yaml` (source of truth), `source/`, `applications/<date>_<company>_<role>/` (each with `meta.json`).
- Web UI: `autocv/api.py` (FastAPI), `autocv/ai.py` (prompts + fact-check repair loop), `autocv/engine.py` (headless `claude -p`, tools disabled — uses the Claude subscription, no API key), `autocv/store.py`, `autocv/jobfetch.py` (JD from URL: ATS APIs → JSON-LD → text → Playwright fallback, SSRF-guarded on every hop), `web/` (React + Vite + Tailwind). The model never writes to the profile: gap answers become *proposals* the user approves in the UI.

## Commands
```
uv run autocv ingest | baseline | new "<Co>" "<Role>" | evidence [term] | check <app> | build <app> | serve
uv run pytest
npm --prefix web run build      # then `uv run autocv serve` → http://127.0.0.1:8000
AUTOCV_ENGINE=fake uv run autocv serve --port 8001   # demo engine, no AI calls
```
