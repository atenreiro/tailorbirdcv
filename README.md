# AutoCV

Tailors a master resume to a job description, **without inventing anything**. A local web UI (FastAPI + React) handles the workflow. The AI work runs on your own Claude Code CLI login, so it uses your Claude subscription with no API key and no per-call billing. Deterministic Python handles the fact-check gate, renders your exact Word design, measures ATS keyword coverage, and converts to PDF through Word.

## How it works
```
JD ─► Analyze ─► Gap questions ─► (you approve new evidence) ─► Compose ─► Fact-check ⟲ repair ─► Review ─► Build
                                                                     │
                       private/profile.yaml (source of truth) ◄── every claim cites it
```
- **Master profile** (`private/profile.yaml`): every achievement, skill and locked field (employer, title, dates, education…), each with an id.
- **Tailored resume**: reorders and rephrases, but every claim cites profile ids. The fact-check rejects any number, tool or name that isn't in the cited evidence. Locked fields are pulled from the profile, so they can't drift.
- **AI engine**: `claude -p` with all tools disabled, run from an empty folder, with output constrained to a JSON schema whose citable ids are limited to ids in your profile. Fact-check failures are fed back to the model automatically, for up to 3 repair rounds.
- **Rendering**: reproduces the original resume's formatting exactly (verified pixel-identical via `autocv baseline`).

## Setup (once)
```bash
uv sync
npm --prefix web install && npm --prefix web run build
cp "<your resume>.docx" private/source/base_resume.docx
uv run autocv ingest && uv run autocv baseline
claude          # in a terminal, then /login, so the CLI has a valid session
```

## Run
```bash
uv run autocv serve        # → http://127.0.0.1:8000
```
- Frontend development: `npm --prefix web run dev` (port 5173, proxies `/api` to 8000).
- Demo without AI calls: `AUTOCV_ENGINE=fake uv run autocv serve --port 8001`.
- `AUTOCV_MODEL` picks the model (e.g. `opus`); the default is the CLI's own default.

The Claude Code skills `/tailor` and `/profile` still work and share the same data.

Everything under `private/` is gitignored. Tests use a fictional profile in `tests/fixtures/`.
