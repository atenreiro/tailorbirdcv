"""AutoCV command line.

    autocv ingest [--force]          base resume → private/profile.yaml (+ base_tailored.yaml)
    autocv baseline                  re-render the base resume; verify text + page count
    autocv new "<Company>" "<Role>"  create an application folder
    autocv evidence [term]           list citable evidence ids (optionally filtered)
    autocv check <app>               fact-check + ATS report (exit 1 on errors)
    autocv build <app>               check → .docx → .pdf → page limit → status "built"
                                     (exit 1 fact-check, 2 too long, 3 PDF failed)
    autocv serve [--port 8000]       start the web UI (localhost only) and open it in the browser
                 [--no-browser]
    autocv doctor                    check this machine: data folder, AI engine, PDF engine, fonts, browser
    autocv install-browser           install the headless browser used for JavaScript-only job pages
    autocv --version
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import logging
import sys
import tempfile
import time
from pathlib import Path

from . import ats, factcheck
from .ingest import ingest, merge_reingest
from .render import docx_text, render
from .schema import MasterProfile, dump_yaml, load_profile, load_tailored, load_yaml

from .store import OutputInUse, Store

PDF_FAILED = 3  # exit code: the PDF couldn't be made (1 = fact-check, 2 = too long)

STORE = Store.default()
PRIVATE = STORE.private
SOURCE_DOCX = STORE.source_docx
PROFILE = STORE.profile_path
BASE_TAILORED = STORE.base_tailored_path
APPS = STORE.apps_dir


def _app(arg: str) -> tuple[str, Path]:
    """An application given as its id (company~yyyy-mm-dd_role), its folder relative to
    applications/ (company/yyyy-mm-dd_role), or any path to the folder."""
    try:
        return arg, STORE.app_path(arg)
    except KeyError:
        pass
    for path in (Path(arg), APPS / arg):
        try:
            if path.is_dir():
                app_id = STORE.app_id_for(path)
                return app_id, STORE.app_path(app_id)
        except (KeyError, ValueError):
            pass
    sys.exit(f"{arg} is not an application under {APPS} (use company~yyyy-mm-dd_role or company/yyyy-mm-dd_role)")


def _app_dir(arg: str) -> tuple[str, Path]:
    app_id, path = _app(arg)
    if not (path / "tailored.yaml").exists():
        sys.exit(f"no tailored.yaml in {path}")
    return app_id, path


def _print_report(report: factcheck.Report) -> None:
    for issue in report.errors:
        print(f"  ERROR   {issue}")
    for issue in report.warnings:
        print(f"  warning {issue}")
    print("fact-check: " + ("PASS" if report.ok else f"FAIL ({len(report.errors)} errors)"))


# --------------------------------------------------------------------------- commands


def cmd_ingest(args) -> int:
    if PROFILE.exists() and not args.force:
        sys.exit(f"{PROFILE} exists — it is the curated source of truth. Use --force to overwrite.")
    profile, base = ingest(SOURCE_DOCX)
    MasterProfile.model_validate(profile)  # never write an invalid source of truth
    with STORE.lock:
        if PROFILE.exists():
            # Re-ingest: keep interview/prep-guide evidence and approved extras, keep ids whose
            # text is unchanged, give changed facts new ids (the old ones are retired).
            try:
                old = STORE.profile()
            except Exception as e:  # noqa: BLE001
                sys.exit(f"{PROFILE} doesn't validate ({e}). Fix it first (or move it aside to ingest from scratch).")
            try:
                profile, base = merge_reingest(old.model_dump(exclude_none=True), profile, base)
            except ValueError as e:
                sys.exit(f"ingest --force aborted: {e}")
        # Through save_profile: ids that disappear are retired, the old profile goes to history.
        STORE.save_profile(profile, cause="ingest force")
    dump_yaml(base, BASE_TAILORED)
    p = load_profile(PROFILE)
    n = sum(len(r.achievements) for r in p.roles)
    print(f"wrote {PROFILE} ({len(p.roles)} roles, {n} achievements, {len(p.highlights)} highlights)")
    print(f"wrote {BASE_TAILORED}")
    return 0


def cmd_baseline(args) -> int:
    profile = load_profile(PROFILE)
    # The baseline checks the Classic design against the original resume, whatever theme is chosen.
    out = render(profile, load_tailored(BASE_TAILORED), PRIVATE / "baseline" / "baseline.docx", theme="classic",
                 paper="letter")
    diff = list(difflib.unified_diff(docx_text(SOURCE_DOCX), docx_text(out), "original", "rebuilt", lineterm="", n=0))
    print("\n".join(diff) if diff else "text: identical to the original")
    report = factcheck.check(profile, load_tailored(BASE_TAILORED))
    _print_report(report)
    if not args.no_pdf:
        from .pdf import page_count, to_pdf
        try:
            print(f"pages: {page_count(to_pdf(out, engine=STORE.settings()['pdf_engine']))}")
        except RuntimeError as e:
            print(f"pdf failed: {e}", file=sys.stderr)
            return PDF_FAILED
    print(f"→ {out}")
    return 0 if report.ok and not diff else 1


def cmd_new(args) -> int:
    app_id = STORE.create_app(args.company, args.role, f"# {args.role} — {args.company}\n\n")
    print(f"{app_id}  →  {STORE.app_path(app_id)}")
    return 0


def cmd_evidence(args) -> int:
    idx = factcheck.evidence_index(load_profile(PROFILE))
    term = (args.term or "").lower()
    for id_, text in idx.items():
        if term in text.lower() or term in id_:
            print(f"{id_}: {text.splitlines()[0]}")
    return 0


def _check(app: Path):
    profile = load_profile(PROFILE)
    tailored = load_tailored(app / "tailored.yaml")
    report = factcheck.check(profile, tailored)
    _print_report(report)
    analysis_path = app / "analysis.yaml"
    if report.ok and analysis_path.exists():
        analysis = load_yaml(analysis_path)
        if analysis.get("keywords"):
            with tempfile.TemporaryDirectory() as tmp:
                lines = docx_text(render(profile, tailored, Path(tmp) / "r.docx"))
            for line in ats.analyze(analysis["keywords"], lines, profile).lines():
                print(f"  ats     {line}")
    return profile, tailored, report


def cmd_check(args) -> int:
    _, _, report = _check(_app_dir(args.app)[1])
    return 0 if report.ok else 1


def cmd_build(args) -> int:
    app_id, app = _app_dir(args.app)
    profile, tailored, report = _check(app)
    if not report.ok:
        print("build blocked: fix the fact-check errors first")
        return 1
    # Render from exactly the bytes that are hashed (a save during the build can't be mislabelled).
    tailored, built_hash, profile, profile_version = STORE.build_inputs(app_id)
    if not factcheck.check(profile, tailored).ok:
        print("build blocked: the resume changed while checking — run build again")
        return 1
    try:
        STORE.clear_outputs(app_id)  # never leave an older .docx/.pdf around
    except OutputInUse as e:
        print(f"build blocked: {e}", file=sys.stderr)
        return PDF_FAILED
    docx = render(profile, tailored, app / f"{STORE.output_stem(app_id)}.docx")
    print(f"docx: {docx}")
    pages, fill = None, None
    if not args.no_pdf:
        from .pdf import page_count, to_pdf
        try:
            pdf = to_pdf(docx, engine=STORE.settings()["pdf_engine"])
        except RuntimeError as e:  # no engine, Word dialog/timeout, PDF open in a viewer…
            STORE.record_build(app_id, built_hash, profile_version, None)
            print(f"pdf failed (the .docx was built): {e}", file=sys.stderr)
            return PDF_FAILED
        pages = page_count(pdf)
        print(f"pdf:  {pdf} ({pages} pages)")
        limit = args.max_pages or int(STORE.settings()["targets"]["pages"])
        from . import ai, fit
        if pages > limit:
            STORE.record_build(app_id, built_hash, profile_version, pages)  # the files on disk are this build
            print(f"TOO LONG: {pages} pages > {limit} — trim lowest-relevance content and rebuild")
            return 2
        try:
            fill = ai.measure_pdf(profile, tailored, pdf, STORE.lock)
        except Exception:  # noqa: BLE001 — measuring never fails a build
            fill = None
        if fill:
            print(f"fill: last page {fill['pages'][-1]:.0%} full" + (
                f" — room for ~{fill['room']} more lines (Fill the page in Export)"
                if fill["room"] >= fit.ROOM_MIN_LINES else ""))
    STORE.record_build(app_id, built_hash, profile_version, pages, fill if pages else None)
    STORE.advance_status(app_id, "built")
    return 0


def _open_when_ready(url: str, port: int, timeout: float = 20.0) -> None:
    """Open the default browser once the server accepts connections."""
    import socket
    import time
    import webbrowser

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.2)


SHUTDOWN_GRACE = 3  # seconds a request still running gets to finish after Ctrl+C


class _QuietShutdown(logging.Filter):
    """Ctrl+C cancels whatever is still running. That's expected, so no tracebacks or alarming errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            return False
        msg = record.getMessage()
        if msg.startswith("Traceback") and msg.rstrip().endswith(("CancelledError", "KeyboardInterrupt")):
            return False  # the app's shutdown step, cut short by a forced quit (logged as text)
        return not ("graceful shutdown exceeded" in msg or msg.startswith("Waiting for"))


def _server_class(uvicorn):
    class Server(uvicorn.Server):
        """A single Ctrl+C often arrives twice (from the terminal and again via `uv run`), which uvicorn
        treats as "force quit" and skips the clean shutdown. Ignore a repeat within a second; a deliberate
        second press later still forces it."""
        first_exit = 0.0

        def handle_exit(self, sig, frame) -> None:
            now = time.monotonic()
            if self.should_exit and now - self.first_exit < 1:
                return
            if not self.should_exit:
                self.first_exit = now
                print(f"\nStopping AutoCV (anything still running gets {SHUTDOWN_GRACE} s to finish)…", flush=True)
            super().handle_exit(sig, frame)
    return Server


def cmd_serve(args) -> int:
    import threading

    import uvicorn

    from .api import create_app
    from .paths import web_dir
    url = f"http://127.0.0.1:{args.port}/?key={STORE.access_key()}"  # unlocks this browser (see api.guard)
    built = web_dir() is not None
    if not built:
        print("note: web UI not built — run `npm --prefix web install && npm --prefix web run build` "
              "(or use `npm --prefix web run dev` on :5173). Serving the API only.")
    print(f"AutoCV → {url}", flush=True)
    print("  (this link unlocks AutoCV in your browser; keep it to yourself)", flush=True)
    if built and not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.port), daemon=True).start()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=args.port,
                            timeout_graceful_shutdown=SHUTDOWN_GRACE)
    logging.getLogger("uvicorn.error").addFilter(_QuietShutdown())
    try:
        _server_class(uvicorn)(config).run()
    except KeyboardInterrupt:  # uvicorn re-raises the Ctrl+C once it has shut down
        pass
    print("AutoCV stopped.", flush=True)
    return 0


def cmd_doctor(args) -> int:
    import asyncio

    from . import doctor
    from .engine import default_engine
    checks = asyncio.run(doctor.run_checks(default_engine(STORE), PRIVATE, STORE.settings()["pdf_engine"]))
    print(doctor.render(checks))
    return 1 if any(c["status"] == "error" for c in checks) else 0


def cmd_install_browser(args) -> int:
    import subprocess
    print("Installing the headless browser for JavaScript-only job pages (about 100 MB)…", flush=True)
    code = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
    if code == 0 and sys.platform.startswith("linux"):
        print("On Linux it may also need system libraries; if pages fail to load, run:\n"
              f"  sudo {sys.executable} -m playwright install-deps chromium")
    return code


def main(argv: list[str] | None = None) -> int:
    from .doctor import version
    parser = argparse.ArgumentParser(prog="autocv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"autocv {version()}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("baseline"); p.add_argument("--no-pdf", action="store_true"); p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("new"); p.add_argument("company"); p.add_argument("role"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("evidence"); p.add_argument("term", nargs="?"); p.set_defaults(fn=cmd_evidence)
    p = sub.add_parser("check"); p.add_argument("app"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("build"); p.add_argument("app"); p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--max-pages", type=int, default=None, help="default: the page limit in Settings"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="don't open the web UI in the default browser")
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("install-browser").set_defaults(fn=cmd_install_browser)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    settings = STORE.settings()
    from . import ai
    from .render import use_design
    ai.use_context(ai.Context.from_settings(settings["targets"], PRIVATE))
    use_design(settings["theme"], settings["paper"])
    if args.cmd not in ("serve", "doctor", "install-browser"):  # serve migrates when the API starts
        try:
            for old, new in STORE.migrate_layout().items():
                print(f"moved application {old} → {STORE.app_path(new).relative_to(STORE.apps_dir)}")
        except Exception as e:  # noqa: BLE001 — never block a command on housekeeping
            print(f"warning: application folder migration failed ({e})", file=sys.stderr)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
