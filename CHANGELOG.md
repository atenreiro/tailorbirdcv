# Changelog

## 0.2.0 — unreleased
- **Runs on macOS, Windows and Linux.** Word is driven hidden on macOS (AppleScript) and Windows (COM); LibreOffice works everywhere, with metric-compatible stand-ins (Gelasio, Carlito) when Microsoft's fonts are missing, so page breaks match Word's.
- **Choose the PDF engine** (Word or LibreOffice) in the new Settings page; Word is the default when both are installed.
- **One-command install:** `uv tool install autocv-app` (or `pipx install autocv-app`); the web UI ships inside the package, so Node isn't needed. User data lives in the OS's per-user data folder.
- `autocv doctor` (also under Settings → System check) explains what's missing and how to fix it; `autocv install-browser` installs the optional headless browser.
- The fact-check's word list is bundled, so it behaves identically on every OS.
- **Works for anyone:** a Welcome page imports any resume (.docx, PDF or text) through the AI, word-for-word, flagging anything that doesn't match the original; or start blank. Settings → *Your targets* (field, seniority, target roles, region, US/UK spelling, 1–3 page limit, domain pack) replaces the built-in cybersecurity/APAC assumptions; the original emphasis lives on as the *Cybersecurity* pack.
- Output files keep accented and non-Latin names (José → `Jose_…`, not `Jos_…`).

## 0.1.0
- First version: fact-locked tailoring, gap questions, memory, hiring-manager review, sent copies and history.
