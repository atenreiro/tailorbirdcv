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
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, a Python tool installer.
- **An AI**, one of:
  - **[Claude Code](https://claude.com/claude-code)**, logged in with your Claude subscription (run `claude`, then `/login`). No extra cost.
  - **[Codex](https://github.com/openai/codex)**, logged in with your ChatGPT subscription (`npm i -g @openai/codex`, then `codex login`). No extra cost.
  - **An API key**, billed per use: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/) or [OpenRouter](https://openrouter.ai/) (which uses the same Claude model by default). Keys are stored in your system's keychain, never in AutoCV's files.
- **Something to make PDFs**: Microsoft Word (macOS, Windows) or the free [LibreOffice](https://www.libreoffice.org/) (all systems). Without either, you still get the Word document.

## Run it
From a copy of this repository (you'll also need [Node.js](https://nodejs.org/) to build the interface once):
```bash
uv sync
npm --prefix web install && npm --prefix web run build
uv run autocv serve
```
Your browser opens AutoCV through a private link (it's also printed in the terminal, starting with `AutoCV →`): it unlocks AutoCV in that browser, so other programs on your computer can't read your data. Press **Ctrl+C** in the terminal to stop AutoCV.

Once AutoCV is published, installing will be a single command, with no Node.js needed:
```bash
uv tool install autocv-app
autocv serve
```

To check that everything AutoCV needs is in place (the AI, PDF engine, fonts):
```bash
uv run autocv doctor
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
5. Track each application under **Applications**. Marking one *applied* keeps a read-only copy of exactly what you sent.

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
