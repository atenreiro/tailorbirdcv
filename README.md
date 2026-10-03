# AutoCV

Tailors a master resume to a job description, **without inventing anything**. A local web UI (FastAPI + React) handles the workflow. The AI work runs on your own Claude Code CLI login, so it uses your Claude subscription with no API key and no per-call billing. Deterministic Python handles the fact-check gate, renders your exact Word design, measures ATS keyword coverage, and converts to PDF through Microsoft Word or LibreOffice. Runs on macOS, Windows and Linux.

## How it works
```
JD ─► Analyze ─► Gap questions ─► (you approve new evidence) ─► Compose ─► Fact-check ⟲ repair ─► Review ─► Build
                                                                     │
                       private/profile.yaml (source of truth) ◄── every claim cites it
```
- **Master profile** (`private/profile.yaml`): every achievement, skill and locked field (employer, title, dates, education…), each with an id.
- **Tailored resume**: reorders and rephrases, but every claim cites profile ids. The fact-check rejects any number, tool or name that isn't in the cited evidence. Locked fields are pulled from the profile, so they can't drift.
- **AI engine**: `claude -p` fully isolated (no tools, MCP servers, plugins, hooks, skills or saved sessions), run from an empty folder, with output constrained to a JSON schema whose citable ids are limited to ids in your profile. Fact-check failures are fed back to the model automatically, for up to 3 repair rounds.
- **Memory** (`private/knowledge.yaml`): every finalized gap answer is remembered. Known gaps aren't asked again, and similar questions are pre-filled. Style preferences are learned from your Review edits and guidance, and applied only once you approve them. Manage both under Master profile → "Answers & gaps" / "Style preferences". Memory steers questions and style; it is never resume evidence.
- **Hiring-manager review**: on demand in Review, the AI reads the draft as the role's hiring manager and a recruiter skimming the top third would. You get a verdict, scores, and specific fixes pinned to lines. Every suggested rewrite is fact-checked before you see it, and you accept or reject each one.
- **Sent copies and history**: marking an application *applied* freezes a read-only copy of exactly what you sent. Every change to your profile and answers is kept in Master profile → History, with a diff and one-click (undoable) restore.
- **Rendering**: reproduces the original resume's formatting exactly (verified pixel-identical via `autocv baseline`).

## Install
You need:
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (or [pipx](https://pipx.pypa.io/)).
- [Claude Code](https://claude.com/claude-code), logged in with your Claude subscription (run `claude`, then `/login`). On Windows, use the native installer (`claude.exe`).
- A PDF engine, chosen in Settings (Word is the default when both are installed):

| | macOS | Windows | Linux |
|---|---|---|---|
| Microsoft Word | ✓ (hidden, via AppleScript) | ✓ (hidden, via COM) | — |
| LibreOffice (free) | ✓ | ✓ | ✓ (`libreoffice-writer` package) |

  Without Microsoft's fonts (typically Linux), LibreOffice uses free look-alikes with identical letter widths (Carlito, and Gelasio which ships with AutoCV), so page breaks still match Word's.

```bash
uv tool install autocv-app     # or: pipx install autocv-app   (or try it once: uvx autocv-app serve)
autocv serve                   # opens http://127.0.0.1:8000 in your browser
autocv doctor                  # optional: checks the AI engine, PDF engine, fonts and browser
autocv install-browser         # optional: headless browser for job pages that need JavaScript (~100 MB)
```
Update with `uv tool upgrade autocv-app` (or `pipx upgrade autocv-app`).

## First run
1. **Import your resume** on the Welcome page: a Word file, a PDF or pasted text, in any layout. The AI copies it into your master profile word-for-word (it doesn't rewrite anything), and anything that doesn't match your file exactly is highlighted for you to check. Nothing is saved until you click *Save as my profile*. Or start with a blank profile.
2. **Settings → Your targets**: your field, seniority, the roles you're aiming for, region, US or UK spelling, and the page limit (1–3). These steer what the AI emphasises; they never add facts. A *domain pack* adds field-specific emphasis (currently: General, Cybersecurity).
3. **New tailoring**: paste a job description (or its URL) and follow the steps.

## Your data stays on your computer
AutoCV runs only on `127.0.0.1`; there's no account, server or telemetry. Your profile, applications and settings live in:
- macOS: `~/Library/Application Support/AutoCV`
- Windows: `%LOCALAPPDATA%\AutoCV`
- Linux: `~/.local/share/AutoCV`

Set `AUTOCV_PRIVATE` to use another folder. The only data that leaves your computer is what the AI engine sends to Claude to analyze and write your resume.

## Development
```bash
git clone https://github.com/atenreiro/autocv && cd autocv
uv sync
npm --prefix web install && npm --prefix web run build
uv run autocv serve            # a source checkout keeps its data in ./private if that folder exists
uv run pytest
```
Releases: bump `version` in `pyproject.toml`, add a CHANGELOG entry, then push a tag `vX.Y.Z`; `.github/workflows/release.yml` builds the UI and publishes `autocv-app` to PyPI.

### Command-line import (AutoCV's own resume layout)
```bash
cp "<your resume>.docx" "<data folder>/source/base_resume.docx"
uv run autocv ingest && uv run autocv baseline
```
To customise the emphasis heuristics for yourself, copy `autocv/data/config/industries.yaml` or `tracks.yaml` to `<data folder>/config/` and edit it.

## Options
- Frontend development: `npm --prefix web run dev` (port 5173, proxies `/api` to 8000).
- Demo without AI calls: `AUTOCV_ENGINE=fake uv run autocv serve --port 8001` (PowerShell: `$env:AUTOCV_ENGINE="fake"; uv run autocv serve --port 8001`).
- LibreOffice in an unusual location: set `AUTOCV_SOFFICE` to its `soffice` (Windows: `soffice.com`) path.
- Job URLs: Lever/Greenhouse/Ashby APIs → embedded JobPosting data → page text → headless Chromium fallback (`AUTOCV_BROWSER_FALLBACK=0` disables it). Every request, browser ones included, is limited to public addresses.
- `AUTOCV_MODEL` picks the model (e.g. `opus`); the default is the CLI's own default.

The Claude Code skills `/tailor` and `/profile` still work and share the same data.

In a source checkout, `private/` is gitignored. Tests use a fictional profile in `tests/fixtures/`.
