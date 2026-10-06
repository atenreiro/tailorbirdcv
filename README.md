<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.png"><img src="docs/logo.png" alt="TailorbirdCV" width="420"></picture></p>

# TailorbirdCV

TailorbirdCV tailors your resume to a specific job, **without inventing anything**.

You give it your CV once. It turns it into a *master profile*: every role, achievement and skill you have. For each job you apply to, paste the job posting's link (or its text). TailorbirdCV then:
- works out what the role cares about;
- asks you about anything the job wants that your profile doesn't cover;
- writes a tailored resume that reorders and rephrases your real experience to fit;
- builds a Word document and a PDF, ready to send.

Every line in a tailored resume must point back to something in your profile. A built-in fact-check blocks any number, tool, employer or claim that isn't there. Your name, employers, job titles, dates and education are always copied exactly as they appear in your profile.

TailorbirdCV is a small web app that runs on your own computer (macOS, Windows or Linux) and opens in your browser. The writing is done by the AI you choose: Claude or ChatGPT through a subscription you already have, or an API key from Anthropic, OpenAI or OpenRouter.

![A tailored resume in Review: every line traces back to the profile, and the fact-check has passed](docs/screenshots/review.png)

## What you need
- **An AI**, one of:
  - **[Claude Code](https://claude.com/claude-code)**, logged in with your Claude subscription (run `claude`, then `/login`). No extra cost.
  - **[Codex](https://github.com/openai/codex)**, logged in with your ChatGPT subscription (macOS: `brew install --cask codex`; Windows/Linux: `npm i -g @openai/codex`; then `codex login`). No extra cost.
  - **An API key**, billed per use: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/) or [OpenRouter](https://openrouter.ai/) (which uses the same Claude model by default). Keys are stored in your system's keychain, never in TailorbirdCV's files.
- **Something to make PDFs**: Microsoft Word (macOS, Windows) or the free [LibreOffice](https://www.libreoffice.org/) (all systems). Without either, you still get the Word document.

## Install
> TailorbirdCV isn't on PyPI yet. Until the first release, use **From a copy of this repository** below.

### macOS
1. Open **Terminal** (press ⌘ Space and type *Terminal*).
2. Paste this line and press Return:
   ```bash
   curl -LsSf https://raw.githubusercontent.com/atenreiro/tailorbirdcv/main/install.sh | sh
   ```
3. TailorbirdCV opens in your browser after a minute or two. Leave the Terminal window open while you use it.

### Windows
1. Open **PowerShell** (Start menu, type *PowerShell*). A normal window: no need to run it as administrator.
2. Paste this line and press Enter:
   ```powershell
   irm https://raw.githubusercontent.com/atenreiro/tailorbirdcv/main/install.ps1 | iex
   ```
3. TailorbirdCV opens in your browser after a minute or two. Leave the PowerShell window open while you use it.

On Linux, the macOS command works too.

### What the installer does
The scripts are short enough to read before you run them: [install.sh](https://github.com/atenreiro/tailorbirdcv/blob/main/install.sh) (macOS, Linux) and [install.ps1](https://github.com/atenreiro/tailorbirdcv/blob/main/install.ps1) (Windows). They:
- install [uv](https://docs.astral.sh/uv/), Astral's open-source Python tool installer, if you don't already have it;
- install TailorbirdCV from PyPI in its own environment, on a Python 3.13 that uv downloads for TailorbirdCV alone. Any Python already on your computer is left alone;
- add the `tailorbirdcv` command to your PATH;
- start TailorbirdCV.

They need no administrator rights, write only inside your user folder, and use your computer's own certificate store, so they also work on company networks that inspect HTTPS.

### Using TailorbirdCV
- **Start:** open Terminal or PowerShell and run `tailorbirdcv serve`. Your browser opens TailorbirdCV through a private link (it's also printed in the terminal, starting with `TailorbirdCV →`). The link unlocks TailorbirdCV in that browser only, so other programs on your computer can't read your data.
- **Stop:** press **Ctrl+C** in that window, or close it.
- **Check your setup** (AI, PDF engine, fonts): `tailorbirdcv doctor`.

### Update
When a new version is out, TailorbirdCV says so at the top of the page. If you installed it with the install line above, click **Upgrade**: TailorbirdCV downloads the new version and restarts (on Windows, in a new terminal window), and the page reloads by itself. Otherwise the notice shows the command to run.

To know about new versions, TailorbirdCV asks PyPI (where it's published) for the latest version number when it opens, at most once a day. Nothing about you or your resumes is sent. Turn it off in **Settings → About TailorbirdCV**.

To update by hand: stop TailorbirdCV, then run the install line again, or `uv tool upgrade tailorbirdcv`.

### Uninstall
Stop TailorbirdCV, then run:
- macOS or Linux:
  ```bash
  curl -LsSf https://raw.githubusercontent.com/atenreiro/tailorbirdcv/main/install.sh | sh -s -- --uninstall
  ```
- Windows:
  ```powershell
  $env:TAILORBIRDCV_UNINSTALL = "1"; irm https://raw.githubusercontent.com/atenreiro/tailorbirdcv/main/install.ps1 | iex
  ```

`uv tool uninstall tailorbirdcv` does the same. Your profile and applications stay in your data folder (see [Your data stays on your computer](#your-data-stays-on-your-computer)) until you delete it. uv stays installed; [Astral's instructions](https://docs.astral.sh/uv/getting-started/installation/#uninstallation) explain how to remove it.

### Install without the script
Install uv yourself (`brew install uv` on macOS, `winget install astral-sh.uv` on Windows, or [another way](https://docs.astral.sh/uv/getting-started/installation/)), open a new terminal, then:
```bash
uv tool install --python 3.13 tailorbirdcv
tailorbirdcv serve
```

### If something goes wrong
| What you see | What to do |
|---|---|
| `command not found: tailorbirdcv`, or *tailorbirdcv is not recognized* | Open a new Terminal or PowerShell window. If it's still not found, run `uv tool update-shell`, then open another new window. |
| *TailorbirdCV is running. Stop it first* | Press Ctrl+C in the window where TailorbirdCV runs (or close it), then run the installer again. |
| *Port 8000 is already in use* | TailorbirdCV is already running: use the link in its window, or start another copy with `tailorbirdcv serve --port 8001`. |
| *Running scripts is disabled on this system* (Windows) | That happens when running a downloaded `install.ps1` file. Use the `irm … \| iex` line above instead. |
| *Don't run this with sudo* (macOS, Linux) | Run the install line again without `sudo`: TailorbirdCV installs for your user only. |
| Downloads fail or time out | Your network may block astral.sh, GitHub or PyPI. Try another network, or ask your IT team to allow them. |

### From a copy of this repository
You'll also need [Node.js](https://nodejs.org/) to build the interface once:
```bash
uv sync
npm --prefix web install && npm --prefix web run build
uv run tailorbirdcv serve
```

## First run: the setup wizard
The first time you open TailorbirdCV, a short wizard (about 5 minutes) sets everything up:
1. **Connect your AI**: choose Claude Code, Codex, or an API key. The page notices on its own once you've logged in.
2. **Upload your CV** as .docx, PDF or plain text. The AI copies it into your master profile word for word; it doesn't rewrite anything.
3. **Review**: check every line. Anything that doesn't match your file exactly is highlighted: fix it, remove it, or confirm it's correct. Then click *Save my profile*. You can also start from a blank profile.
4. **Your targets**, pre-filled from your CV: your field, seniority, the roles you want, region, US or UK spelling, and page limit. These guide what gets emphasised; they never add facts.
5. **Design**: Classic, Modern or Compact, on A4 or US Letter.
6. **Final checks**: the PDF engine, fonts, and an optional helper for job sites that need a full browser.

You can change any of this later in **Settings**, and run the wizard again from there.

![The setup wizard's review step: the CV as TailorbirdCV read it, checked line by line against the file](docs/screenshots/setup.png)

## Everyday use
1. Open **New tailoring** and paste the job posting's URL (or its text).
2. Answer any questions about gaps. If you don't have the experience, say so: it stays a gap.
3. Review the draft and edit it if you like. You can also ask for a hiring-manager review.
4. Build the Word document and PDF.
5. Track each application under **Applications**. Marking one *applied* keeps a read-only copy of exactly what you sent. Found one of your resumes somewhere and not sure which version it is? **Identify a PDF** in Applications tells you which application it came from, using the exact file's SHA-256 or the PDF's own document id. Nothing is ever added to your PDFs.

![The brief: what the role wants, and how your evidence stacks up against each requirement](docs/screenshots/brief.png)

![Gap questions: TailorbirdCV asks about what the job wants and your profile doesn't show](docs/screenshots/gaps.png)

The screenshots use a fictional profile and job posting.

## Your data stays on your computer
> [!IMPORTANT]
> **The only thing that leaves your computer is what the AI needs to read your CV and the job, and to write the resume.**

TailorbirdCV only runs locally. There's no account, no server and no tracking. Your profile, applications and settings are kept in:
- macOS: `~/Library/Application Support/TailorbirdCV`
- Windows: `%LOCALAPPDATA%\TailorbirdCV`
- Linux: `~/.local/share/TailorbirdCV`

For each application made from a job link, TailorbirdCV fetches the company's site icon once, from the company's own website (never a job board's logo), and keeps it with the application. **Settings → Applications → Show company icons** turns this off: no icons shown, none fetched.

**Privacy mode** (Settings → Privacy, on by default, **experimental**): your name, email, phone, street address and personal links (LinkedIn, GitHub, your own website), and any other email address or phone number in what you type, are replaced by placeholders like `[NAME]` before anything is sent to the AI, and put back in its answers. Your resume still shows them: TailorbirdCV prints them itself. The setup wizard asks for your name before reading your CV, so it's hidden from the first step. It matches your details as written and common formats, so an unusual spelling can slip through; your career history is still sent and can identify you, and other people's names aren't detected. Use it with care, and check **See what the AI receives** in Settings.

In a copy of this repository that has a `private/` folder, TailorbirdCV uses that folder instead (it's never committed). To use any other folder, set `TAILORBIRDCV_PRIVATE` to its path.

### Backup and restore
Because everything lives only on your computer, keep a backup. **Settings → Backup & restore → Download backup** saves your profile, memory, applications (including the copies you sent), settings and history as one `.zip`. On a new computer, choose **Restore from a backup** on the first setup page (or later in Settings). Restoring never deletes anything: the data it replaces is kept in a `before-restore` folder inside your data folder. From a terminal: `tailorbirdcv backup [file]` and `tailorbirdcv restore <file>`.

> [!WARNING]
> **A backup isn't encrypted.** Anyone who has the file can read your CV, contact details and applications, and use your API keys if you chose to include them (they're left out unless you tick **Include my API keys**). Keep it somewhere private, such as an encrypted drive or your own cloud folder, and don't share it.

## For developers
```bash
uv run pytest                                        # tests
npm --prefix web run dev                             # interface with live reload (port 5173)
TAILORBIRDCV_ENGINE=fake uv run tailorbirdcv serve --port 8001   # demo mode, no AI calls
```
To release a new version: change the number in [VERSION](VERSION) (and add a CHANGELOG entry), then push to `main` (automatic releases are on once the repository variable `RELEASES_ENABLED` is `true`). Once CI passes, the release workflow publishes that version to PyPI and tags it, and installed copies offer the upgrade within a day.

The rules TailorbirdCV follows and how the code is laid out are described in [CLAUDE.md](CLAUDE.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
