# AutoCV

Tailors the user's resume to a job description without inventing anything. Senior cybersecurity roles (IC or manager) across banking, tech, quant, fintech, telco; Singapore/APAC; max 2 pages; US spelling.

## Non-negotiable rules
1. **Never invent.** Every claim in a tailored resume must trace to `private/profile.yaml`. No new numbers, tools, employers, scope, outcomes, or implied experience — not even "familiar with". If the JD wants something the profile lacks, **ask the user**; if he has no real experience, it stays a gap.
2. **Locked fields never change**: contact, employer, location, job title, dates, education, certifications, awards, languages. The renderer pulls them from the profile by id — never retype them.
3. **The profile changes only with the user's explicit confirmation of the exact wording.** New evidence gets `source: interview` or `source: prep_guide` and `in_base_resume: false`.
4. **Rephrasing is allowed** (reorder, merge, trim, mirror JD vocabulary) as long as the meaning, numbers and entities are unchanged and each claim cites its `sources`. Don't upgrade verbs ("contributed to" → "led") or scope ("team" → "organization").
5. `uv run autocv check` must PASS before `build`. Bullets may only cite their own role's evidence; role header ids aren't citable. Fix violations by citing the right evidence or rewording; never by adding vocabulary or synonyms without the user's approval.
6. Personal data lives only in `private/` (gitignored). Never commit it, never paste it into tests — tests use `tests/fixtures/` (fictional).

## Layout
- `autocv/` — `schema.py` (models), `ingest.py` (docx → profile), `render.py` (pixel-faithful docx), `factcheck.py` (blocking gate), `ats.py` (keyword coverage), `pdf.py` (Word/LibreOffice → PDF), `cli.py`.
- `autocv/data/` (shipped in the package): `config/industries.yaml`, `config/tracks.yaml` — emphasis heuristics only, never facts; `templates/base.docx` — theme/page setup with empty body, no PII; `fonts/` (Gelasio, OFL); `words.txt.gz` (fact-check word list). Never put personal data here.
- `autocv/paths.py` — where things live: bundled data, the built UI (`autocv/web/` in a wheel, `web/dist/` in a checkout), and the user's data (`AUTOCV_PRIVATE`, else `./private` in a checkout that has one, else the OS per-user data folder via platformdirs).
- Packaging: PyPI name `autocv-app` (commands `autocv` and `autocv-app`); `hatch_build.py` puts `web/dist` into the wheel as `autocv/web` (run the web build first). `autocv/doctor.py` backs `autocv doctor` and `GET /api/doctor`. Releases: tag `vX.Y.Z` → `.github/workflows/release.yml` → PyPI (trusted publishing). No licence has been chosen yet: don't add one.
- `.claude/skills/profile` (`/profile`) and `.claude/skills/tailor` (`/tailor`).
- `private/` (the data folder) — `profile.yaml` (source of truth), `knowledge.yaml` (memory: past gap answers + approved style preferences, **never citable**), `source/`, `applications/<company>/<yyyy-mm-dd>_<role>/` (id `<company>~<yyyy-mm-dd>_<role>`; `meta.json`, `answers.yaml`, `tailored.ai.yaml` = AI draft, `tailored.yaml` = edited).
- Web UI: `autocv/api.py` (FastAPI), `autocv/ai.py` (prompts + fact-check repair loop), `autocv/engine.py` (headless `claude -p`, tools disabled — uses the Claude subscription, no API key), `autocv/store.py`, `autocv/jobfetch.py` (JD from URL: ATS APIs → JSON-LD → text → Playwright fallback, SSRF-guarded on every hop), `web/` (React + Vite + Tailwind). The model never writes to the profile: gap answers become *proposals* the user approves in the UI.

## Web API conventions
- Every non-GET `/api/*` request must send `X-AutoCV: 1` (cross-site guard); any `/api/*` request with `Sec-Fetch-Site` other than `same-origin`/`none` is refused. Profile/knowledge PUTs send `If-Match: <version>`; 409 means reload.
- Private files are written atomically under a process-wide lock (`store.lock`); never hold it across an AI call.
- Deleted evidence/knowledge ids are retired (`retired_ids`) and never reused: saves that re-introduce one are rejected, and `ingest --force` keeps them (changed text gets a new id).
- URL fetching goes through `jobfetch.pinned_client()` (PinnedBackend: resolve once, validate every address, connect to the validated one). The headless browser's requests are performed by that client too, never by Chromium's network stack.
- The AI engine runs fully isolated (`engine.ISOLATION_ARGS`): no tools, MCP, user/local settings, plugins, hooks, skills or sessions.
- Hiring-manager review (`autocv/critique.py`): on-demand verdict/scores/skim + issues pinned to claims by their original text; every suggested rewrite is fact-checked before it's shown (failures become advice); fixes needing new info become `hm-` questions in Gaps; accepted/rejected decisions live in `review.yaml` and feed style learning.
- Closing an application sets status `closed` plus an **outcome** (rejected, no_response, role_closed, withdrew, declined_offer, did_not_apply, accepted_offer); the stage it reached comes from its funnel milestones. Old `rejected`/`withdrawn` statuses migrate automatically.
- Builds record `built_hash` (the exact draft bytes rendered) and `built_profile` (a fingerprint of the profile parts that resume prints). Freezing requires both to match AND the current draft to pass the fact-check against the current profile.
- AI Trim never saves: `/trim` returns a fact-checked `trim_proposal` that the UI loads into Review as unsaved edits.
- Marking an application **applied** freezes a read-only copy of exactly what was sent (`sent/<timestamp>/`); stale or missing PDFs → "Build & freeze". Never edit `sent/`.
- Every save of `profile.yaml`/`knowledge.yaml` keeps the previous version in `private/history/` (content changes only; kept forever); restore is itself undoable and merges `retired_ids`.
- PDFs come from **Microsoft Word or LibreOffice** (`pdf.py`), chosen in Settings (`private/settings.json`, `GET/PUT /api/settings`); when both are installed Word is the default, and a chosen engine that's missing falls back to the other. One conversion runs at a time (thread lock + `oscompat.FileLock` in `private/word/`, so CLI and server take turns), always in that fixed folder (Word's macOS sandbox "Grant File Access" prompt appears at most once).
  - Word, macOS: `osascript` JXA — launched hidden in the background, never activated; our document is addressed only by its unique name (never by position), and Word is quit only if AutoCV started it and its document count is 0 (`saving: ask`).
  - Word, Windows: PowerShell 5.1 COM (`-EncodedCommand`) — our document opens with `Visible=$false`, is closed through its own object, and Word is quit only if AutoCV created that instance and `Documents.Count -eq 0`. No Word on Linux.
  - LibreOffice runs headless with its own profile (`private/libreoffice/`); fonts the docx names are symlinked (copied on Windows) into the profile, and a font this machine lacks gets a metric-compatible stand-in through a replacement rule in the profile (Georgia → Gelasio, bundled in `autocv/data/fonts`; Calibri → Carlito). Digit ranges ("2–4") inside `<w:t>` text runs are glued with U+2060 in LibreOffice's copy only — never in the user's .docx.
- OS differences live in `autocv/oscompat.py` (file lock, process-tree kill, read-only-safe `rmtree`, retrying `replace`, reveal in Finder/Explorer/file manager). Files are written with `\n` line endings so hashes match across OSes; folder slugs never use Windows-reserved names (`con`, `nul`, `com1`…).
- The fact-check's word list is bundled (`autocv/data/words.txt.gz`, public-domain web2 — the same list macOS ships), so the gate behaves identically on every OS. CI (`.github/workflows/ci.yml`) runs the tests on macOS, Windows and Linux, plus real LibreOffice conversions on Linux and Windows.
- Compose fits the draft to the base resume's length (estimated lines) with automatic trim rounds; Word's page count is the final check.

## Commands
```
uv run autocv ingest | baseline | new "<Co>" "<Role>" | evidence [term] | check <app> | build <app> | serve | doctor | install-browser
uv run pytest
npm --prefix web run build && uv build   # wheel + sdist in dist/ (the wheel includes the UI)
npm --prefix web run build      # then `uv run autocv serve` → http://127.0.0.1:8000
AUTOCV_ENGINE=fake uv run autocv serve --port 8001   # demo engine, no AI calls
```
