"""Where AutoCV finds its bundled files and keeps the user's data.

- Bundled, read-only: `autocv/data/` (config, Word template, fonts, word list) and the built web UI
  (`autocv/web/` in an installed package, `web/dist/` in a source checkout).
- The user's data (profile, applications, settings): `AUTOCV_PRIVATE` if set; else `private/` in a
  source checkout that already has one (development); else the per-user data folder of the OS:
  macOS `~/Library/Application Support/AutoCV`, Windows `%LOCALAPPDATA%\\AutoCV`,
  Linux `~/.local/share/AutoCV`.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
CHECKOUT = PACKAGE.parent  # the repository root when running from source


def is_checkout() -> bool:
    return (CHECKOUT / "pyproject.toml").is_file() and (CHECKOUT / "autocv" / "__init__.py").is_file()


def private_dir() -> Path:
    if env := os.environ.get("AUTOCV_PRIVATE"):
        return Path(env)
    if is_checkout() and (CHECKOUT / "private").is_dir():
        return CHECKOUT / "private"
    return Path(user_data_dir("AutoCV", appauthor=False))


def web_dir() -> Path | None:
    """The built web UI, or None (then only the API is served)."""
    for folder in (PACKAGE / "web", CHECKOUT / "web" / "dist"):
        if (folder / "index.html").is_file():
            return folder
    return None
