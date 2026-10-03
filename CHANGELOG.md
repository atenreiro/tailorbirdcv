# Changelog

## 0.2.0 — unreleased
- **Runs on macOS, Windows and Linux.** Word is driven hidden on macOS (AppleScript) and Windows (COM); LibreOffice works everywhere, with metric-compatible stand-ins (Gelasio, Carlito) when Microsoft's fonts are missing, so page breaks match Word's.
- **Choose the PDF engine** (Word or LibreOffice) in the new Settings page; Word is the default when both are installed.
- **One-command install:** `uv tool install autocv-app` (or `pipx install autocv-app`); the web UI ships inside the package, so Node isn't needed. User data lives in the OS's per-user data folder.
- `autocv doctor` (also under Settings → System check) explains what's missing and how to fix it; `autocv install-browser` installs the optional headless browser.
- The fact-check's word list is bundled, so it behaves identically on every OS.
- **Works for anyone:** a Welcome page imports any resume (.docx, PDF or text) through the AI, word-for-word, flagging anything that doesn't match the original; or start blank. Settings → *Your targets* (field, seniority, target roles, region, US/UK spelling, 1–3 page limit, domain pack) replaces the built-in cybersecurity/APAC assumptions; the original emphasis lives on as the *Cybersecurity* pack.
- **Resume themes**: Classic (the original design, unchanged), Modern and Compact, on US Letter or A4 (Settings → Resume design). Length estimates follow the theme and paper.
- **Setup wizard** on first run: connect Claude, upload your CV, review every line (anything not word-for-word in your file must be fixed, removed or confirmed; the server checks again), targets suggested from your CV, design, and final checks with a one-click headless-browser install. Progress and the imported draft survive a refresh.
- Robustness: Windows Word conversions take paths via environment variables, report errors as plain text and stop the Word instance they started on a timeout; Carlito ships with AutoCV (Calibri stand-in on Linux); a re-created profile never reuses old ids; Word's lock file survives rebuilds; the CLI reports PDF failures with exit code 3 instead of a traceback; the release workflow runs the tests first, and CI covers Python 3.11.
- **Choice of AI engine** (Settings → AI engine): Claude Code on your subscription, or an Anthropic API key (pay per use), stored in the OS keychain. Switching takes effect immediately; *Test* checks it.
- Output files keep accented and non-Latin names (José → `Jose_…`, not `Jos_…`).

## 0.1.0
- First version: fact-locked tailoring, gap questions, memory, hiring-manager review, sent copies and history.
