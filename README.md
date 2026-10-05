<p align="center"><img src="docs/logo.png" alt="AutoCV" width="240"></p>

# AutoCV

AutoCV tailors your resume to a specific job, **without inventing anything**.

You give it your CV once. It turns it into a *master profile*: every role, achievement and skill you have. For each job you apply to, paste the job posting's link (or its text). AutoCV then:
- works out what the role cares about;
- asks you about anything the job wants that your profile doesn't cover;
- writes a tailored resume that reorders and rephrases your real experience to fit;
- builds a Word document and a PDF, ready to send.

Every line in a tailored resume must point back to something in your profile. A built-in fact-check blocks any number, tool, employer or claim that isn't there. Your name, employers, job titles, dates and education are always copied exactly as they appear in your profile.

AutoCV is a small web app that runs on your own computer (macOS, Windows or Linux) and opens in your browser. The writing is done by the AI you choose: Claude or ChatGPT through a subscription you already have, or an API key from Anthropic, OpenAI or OpenRouter.

![A tailored resume in Review: every line traces back to the profile, and the fact-check has passed](docs/screenshots/review.png)

## What you need
- **An AI**, one of:
  - **[Claude Code](https://claude.com/claude-code)**, logged in with your Claude subscription (run `claude`, then `/login`). No extra cost.
  - **[Codex](https://github.com/openai/codex)**, logged in with your ChatGPT subscription (macOS: `brew install --cask codex`; Windows/Linux: `npm i -g @openai/codex`; then `codex login`). No extra cost.
  - **An API key**, billed per use: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/) or [OpenRouter](https://openrouter.ai/) (which uses the same Claude model by default). Keys are stored in your system's keychain, never in AutoCV's files.
- **Something to make PDFs**: Microsoft Word (macOS, Windows) or the free [LibreOffice](https://www.libreoffice.org/) (all systems). Without either, you still get the Word document.

## Install
> AutoCV isn't on PyPI yet. Until the first release, use **From a copy of this repository** below.

### macOS
1. Open **Terminal** (press ⌘ Space and type *Terminal*).
2. Paste this line and press Return:
   ```bash
   curl -LsSf https://raw.githubusercontent.com/atenreiro/autocv/main/install.sh | sh
   ```
3. AutoCV opens in your browser after a minute or two. Leave the Terminal window open while you use it.

### Windows
1. Open **PowerShell** (Start menu, type *PowerShell*). A normal window: no need to run it as administrator.
2. Paste this line and press Enter:
   ```powershell
   irm https://raw.githubusercontent.com/atenreiro/autocv/main/install.ps1 | iex
   ```
3. AutoCV opens in your browser after a minute or two. Leave the PowerShell window open while you use it.

On Linux, the macOS command works too.

### What the installer does
The scripts are short enough to read before you run them: [install.sh](https://github.com/atenreiro/autocv/blob/main/install.sh) (macOS, Linux) and [install.ps1](https://github.com/atenreiro/autocv/blob/main/install.ps1) (Windows). They:
- install [uv](https://docs.astral.sh/uv/), Astral's open-source Python tool installer, if you don't already have it;
- install AutoCV from PyPI in its own environment, on a Python 3.13 that uv downloads for AutoCV alone. Any Python already on your computer is left alone;
- add the `autocv` command to your PATH;
- start AutoCV.

They need no administrator rights, write only inside your user folder, and use your computer's own certificate store, so they also work on company networks that inspect HTTPS.

### Using AutoCV
- **Start:** open Terminal or PowerShell and run `autocv serve`. Your browser opens AutoCV through a private link (it's also printed in the terminal, starting with `AutoCV →`). The link unlocks AutoCV in that browser only, so other programs on your computer can't read your data.
- **Stop:** press **Ctrl+C** in that window, or close it.
- **Check your setup** (AI, PDF engine, fonts): `autocv doctor`.

### Update
Stop AutoCV, then run the install line again. `uv tool upgrade autocv-app` also works.

### Uninstall
Stop AutoCV, then run:
- macOS or Linux:
  ```bash
  curl -LsSf https://raw.githubusercontent.com/atenreiro/autocv/main/install.sh | sh -s -- --uninstall
  ```
- Windows:
  ```powershell
  $env:AUTOCV_UNINSTALL = "1"; irm https://raw.githubusercontent.com/atenreiro/autocv/main/install.ps1 | iex
  ```

`uv tool uninstall autocv-app` does the same. Your profile and applications stay in your data folder (see [Your data stays on your computer](#your-data-stays-on-your-computer)) until you delete it. uv stays installed; [Astral's instructions](https://docs.astral.sh/uv/getting-started/installation/#uninstallation) explain how to remove it.

### Install without the script
Install uv yourself (`brew install uv` on macOS, `winget install astral-sh.uv` on Windows, or [another way](https://docs.astral.sh/uv/getting-started/installation/)), open a new terminal, then:
```bash
uv tool install --python 3.13 autocv-app
autocv serve
```

### If something goes wrong
| What you see | What to do |
|---|---|
| `command not found: autocv`, or *autocv is not recognized* | Open a new Terminal or PowerShell window. If it's still not found, run `uv tool update-shell`, then open another new window. |
| *AutoCV is running. Stop it first* | Press Ctrl+C in the window where AutoCV runs (or close it), then run the installer again. |
| *Port 8000 is already in use* | AutoCV is already running: use the link in its window, or start another copy with `autocv serve --port 8001`. |
| *Running scripts is disabled on this system* (Windows) | That happens when running a downloaded `install.ps1` file. Use the `irm … \| iex` line above instead. |
| *Don't run this with sudo* (macOS, Linux) | Run the install line again without `sudo`: AutoCV installs for your user only. |
| Downloads fail or time out | Your network may block astral.sh, GitHub or PyPI. Try another network, or ask your IT team to allow them. |

### From a copy of this repository
You'll also need [Node.js](https://nodejs.org/) to build the interface once:
```bash
uv sync
npm --prefix web install && npm --prefix web run build
uv run autocv serve
```

## First run: the setup wizard
The first time you open AutoCV, a short wizard (about 5 minutes) sets everything up:
1. **Connect your AI**: choose Claude Code, Codex, or an API key. The page notices on its own once you've logged in.
2. **Upload your CV** as .docx, PDF or plain text. The AI copies it into your master profile word for word; it doesn't rewrite anything.
3. **Review**: check every line. Anything that doesn't match your file exactly is highlighted: fix it, remove it, or confirm it's correct. Then click *Save my profile*. You can also start from a blank profile.
4. **Your targets**, pre-filled from your CV: your field, seniority, the roles you want, region, US or UK spelling, and page limit. These guide what gets emphasised; they never add facts.
5. **Design**: Classic, Modern or Compact, on A4 or US Letter.
6. **Final checks**: the PDF engine, fonts, and an optional helper for job sites that need a full browser.

You can change any of this later in **Settings**, and run the wizard again from there.

![The setup wizard's review step: the CV as AutoCV read it, checked line by line against the file](docs/screenshots/setup.png)

## Everyday use
1. Open **New tailoring** and paste the job posting's URL (or its text).
2. Answer any questions about gaps. If you don't have the experience, say so: it stays a gap.
3. Review the draft and edit it if you like. You can also ask for a hiring-manager review.
4. Build the Word document and PDF.
5. Track each application under **Applications**. Marking one *applied* keeps a read-only copy of exactly what you sent. Found one of your resumes somewhere and not sure which version it is? **Identify a PDF** in Applications tells you which application it came from, using the exact file's SHA-256 or the PDF's own document id. Nothing is ever added to your PDFs.

![The brief: what the role wants, and how your evidence stacks up against each requirement](docs/screenshots/brief.png)

![Gap questions: AutoCV asks about what the job wants and your profile doesn't show](docs/screenshots/gaps.png)

The screenshots use a fictional profile and job posting.

## Your data stays on your computer
AutoCV only runs locally. There's no account, no server and no tracking. Your profile, applications and settings are kept in:
- macOS: `~/Library/Application Support/AutoCV`
- Windows: `%LOCALAPPDATA%\AutoCV`
- Linux: `~/.local/share/AutoCV`

In a copy of this repository that has a `private/` folder, AutoCV uses that folder instead (it's never committed). To use any other folder, set `AUTOCV_PRIVATE` to its path.

The only thing that leaves your computer is what the AI needs to read your CV and the job, and to write the resume.

## For developers
```bash
uv run pytest                                        # tests
npm --prefix web run dev                             # interface with live reload (port 5173)
AUTOCV_ENGINE=fake uv run autocv serve --port 8001   # demo mode, no AI calls
```
The rules AutoCV follows and how the code is laid out are described in [CLAUDE.md](CLAUDE.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
