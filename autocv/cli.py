"""AutoCV command line.

    autocv ingest [--force]          base resume → private/profile.yaml (+ base_tailored.yaml)
    autocv baseline                  re-render the base resume; verify text + page count
    autocv new "<Company>" "<Role>"  create an application folder
    autocv evidence [term]           list citable evidence ids (optionally filtered)
    autocv check <app_dir>           fact-check + ATS report (exit 1 on errors)
    autocv build <app_dir>           check → .docx → .pdf → page limit → status "built"
    autocv serve [--port 8000]       start the web UI (localhost only) and open it in the browser
                 [--no-browser]
"""

from __future__ import annotations

import argparse
import difflib
import sys
import tempfile
from pathlib import Path

from . import ats, factcheck
from .ingest import ingest
from .render import docx_text, render
from .schema import dump_yaml, load_profile, load_tailored, load_yaml

from .store import Store

STORE = Store.default()
PRIVATE = STORE.private
SOURCE_DOCX = STORE.source_docx
PROFILE = STORE.profile_path
BASE_TAILORED = STORE.base_tailored_path
APPS = STORE.apps_dir
MAX_PAGES = 2


def _app_dir(arg: str) -> Path:
    path = Path(arg)
    if not path.exists() and (APPS / arg).exists():
        path = APPS / arg
    if path.resolve().parent != APPS.resolve():
        sys.exit(f"{path} is not an application folder under {APPS}")
    if not (path / "tailored.yaml").exists():
        sys.exit(f"no tailored.yaml in {path}")
    return path


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
    dump_yaml(profile, PROFILE)
    dump_yaml(base, BASE_TAILORED)
    p = load_profile(PROFILE)
    n = sum(len(r.achievements) for r in p.roles)
    print(f"wrote {PROFILE} ({len(p.roles)} roles, {n} achievements, {len(p.highlights)} highlights)")
    print(f"wrote {BASE_TAILORED}")
    return 0


def cmd_baseline(args) -> int:
    profile = load_profile(PROFILE)
    out = render(profile, load_tailored(BASE_TAILORED), PRIVATE / "baseline" / "baseline.docx")
    diff = list(difflib.unified_diff(docx_text(SOURCE_DOCX), docx_text(out), "original", "rebuilt", lineterm="", n=0))
    print("\n".join(diff) if diff else "text: identical to the original")
    report = factcheck.check(profile, load_tailored(BASE_TAILORED))
    _print_report(report)
    if not args.no_pdf:
        from .pdf import page_count, to_pdf
        print(f"pages: {page_count(to_pdf(out))}")
    print(f"→ {out}")
    return 0 if report.ok and not diff else 1


def cmd_new(args) -> int:
    app_id = STORE.create_app(args.company, args.role, f"# {args.role} — {args.company}\n\n")
    print(APPS / app_id)
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
    _, _, report = _check(_app_dir(args.app))
    return 0 if report.ok else 1


def cmd_build(args) -> int:
    app = _app_dir(args.app)
    profile, tailored, report = _check(app)
    if not report.ok:
        print("build blocked: fix the fact-check errors first")
        return 1
    analysis = load_yaml(app / "analysis.yaml") if (app / "analysis.yaml").exists() else {}
    if not (app / "meta.json").exists():
        STORE.save_meta(app.name, {"company": analysis.get("company") or app.name.split("_")[1],
                                   "role": analysis.get("role", ""), "status": "draft"})
    STORE.clear_outputs(app.name)  # never leave an older .docx/.pdf around
    built_hash = STORE.tailored_hash(app.name)
    docx = render(profile, tailored, app / f"{STORE.output_stem(app.name)}.docx")
    print(f"docx: {docx}")
    pages = None
    if not args.no_pdf:
        from .pdf import page_count, to_pdf
        pdf = to_pdf(docx)
        pages = page_count(pdf)
        print(f"pdf:  {pdf} ({pages} pages)")
        if pages > args.max_pages:
            print(f"TOO LONG: {pages} pages > {args.max_pages} — trim lowest-relevance content and rebuild")
            return 2
    STORE.update_meta(app.name, built_hash=built_hash, pages=pages)
    STORE.advance_status(app.name, "built")
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


def cmd_serve(args) -> int:
    import threading

    import uvicorn

    from .api import create_app
    from .store import ROOT
    url = f"http://127.0.0.1:{args.port}"
    built = (ROOT / "web" / "dist").exists()
    if not built:
        print("note: web UI not built — run `npm --prefix web install && npm --prefix web run build` "
              "(or use `npm --prefix web run dev` on :5173). Serving the API only.")
    print(f"AutoCV → {url}", flush=True)
    if built and not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.port), daemon=True).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autocv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("baseline"); p.add_argument("--no-pdf", action="store_true"); p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("new"); p.add_argument("company"); p.add_argument("role"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("evidence"); p.add_argument("term", nargs="?"); p.set_defaults(fn=cmd_evidence)
    p = sub.add_parser("check"); p.add_argument("app"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("build"); p.add_argument("app"); p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="don't open the web UI in the default browser")
    p.set_defaults(fn=cmd_serve)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
