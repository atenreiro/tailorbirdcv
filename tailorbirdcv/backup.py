"""Backup and restore: the user's data folder as one .zip, to keep safe or to move to another computer.

A backup holds the user's data only (profile, memory, their history, settings, applications with what was
sent, the source CV, personal config) — never this computer's own files (the web UI's access key, PDF-engine
work folders, learned page calibration, update state). API keys stay in the keychain unless the user asks for
them, then they're in `keys.json`. The file is a plain .zip (not encrypted): `WARNING` says so after every
backup.

Restore checks the whole file before touching anything (format, every path, sizes, each file's SHA-256, a
readable profile), unpacks it next to the data, then swaps it in; the data it replaces is kept in
`before-restore/<time>/`, never deleted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import apikey, oscompat, update

FORMAT = 1
MANIFEST = "tailorbirdcv-backup.json"
KEYS = "keys.json"
INCLUDE = ("profile.yaml", "knowledge.yaml", "settings.json", "history", "applications", "source", "config")
KEPT = "before-restore"         # where a restore puts the data it replaced (never part of a backup)
MAX_BYTES = 1_000_000_000      # unpacked size limit (a real backup is a few MB)
MAX_FILES = 50_000

WARNING = ("Keep this backup safe: it isn't encrypted, so anyone who has the file can read your CV, contact "
           "details and applications{keys}. Store it somewhere private (for example an encrypted drive or your "
           "own cloud folder) and don't share it.")


class BackupError(ValueError):
    pass


def warning(keys: bool) -> str:
    return WARNING.format(keys=", and use your API keys" if keys else "")


def file_name(now: dt.datetime | None = None) -> str:
    return f"TailorbirdCV-backup-{(now or dt.datetime.now()):%Y-%m-%d}.zip"


def _skip(path: Path) -> bool:
    name = path.name
    return name == ".DS_Store" or name.startswith("~$") or (name.startswith(".") and name.endswith(".tmp"))


def _files(private: Path):
    for top in INCLUDE:
        root = private / top
        if root.is_file():
            yield root
        elif root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and not _skip(path):
                    yield path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create(store, out: Path, include_keys: bool = False) -> dict:
    """Write a backup of `store`'s data folder to `out`. Returns {files, bytes, keys}: what's in it."""
    private = store.private
    files: dict[str, dict] = {}
    keys: dict[str, str] = {}
    if include_keys:
        for provider in apikey.PROVIDERS:
            key, source = apikey.get(provider)
            if key and source == "keychain":
                keys[provider] = key
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    os.close(fd)
    try:
        with store.lock, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for path in _files(private):
                rel = path.relative_to(private).as_posix()
                data = oscompat.read_bytes(path)
                z.writestr(f"data/{rel}", data)
                files[rel] = {"size": len(data), "sha256": _sha(data)}
            if keys:
                z.writestr(KEYS, json.dumps(keys, indent=2))
            manifest = {"format": FORMAT, "app": "tailorbirdcv", "version": update.current(),
                        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                        "keys": sorted(keys), "files": files}
            z.writestr(MANIFEST, json.dumps(manifest, indent=2))
        oscompat.replace(tmp, out)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return {"files": len(files), "bytes": sum(f["size"] for f in files.values()), "keys": sorted(keys)}


@dataclass
class Contents:
    manifest: dict
    applications: int

    @property
    def summary(self) -> dict:
        m = self.manifest
        return {"created": m.get("created"), "version": m.get("version"), "files": len(m["files"]),
                "applications": self.applications, "keys": m.get("keys", [])}


def inspect(path: Path) -> Contents:
    """Check a backup without unpacking it: a TailorbirdCV backup this version can read, with safe paths
    and a sane size. Raises BackupError with a message for the user."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError("That file isn't a TailorbirdCV backup (it isn't a .zip file).") from e
    with z:
        try:
            manifest = json.loads(z.read(MANIFEST))
        except KeyError as e:
            raise BackupError("That .zip isn't a TailorbirdCV backup (it has no backup manifest).") from e
        except (ValueError, zipfile.BadZipFile) as e:
            raise BackupError("That backup is damaged (its manifest can't be read).") from e
        if not isinstance(manifest, dict) or manifest.get("app") != "tailorbirdcv" \
                or not isinstance(manifest.get("files"), dict):
            raise BackupError("That .zip isn't a TailorbirdCV backup.")
        if not isinstance(manifest.get("format"), int) or manifest["format"] > FORMAT:
            raise BackupError(f"That backup was made by a newer TailorbirdCV ({manifest.get('version', '?')}). "
                              "Update TailorbirdCV, then restore it.")
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
            raise BackupError("That backup is too large to restore.")
        names = {i.filename for i in infos if not i.is_dir()}
        for name in names:
            if name in (MANIFEST, KEYS):
                continue
            rel = _relative(name)
            if rel not in manifest["files"]:
                raise BackupError("That backup is damaged (it has files its manifest doesn't list).")
        for rel in manifest["files"]:
            if not isinstance(rel, str) or _relative("data/" + rel) != rel:  # only exact, canonical paths
                raise BackupError("That backup is damaged or unsafe (it has a file outside the data folder).")
            if f"data/{rel}" not in names:
                raise BackupError("That backup is incomplete (files listed in it are missing).")
        if "profile.yaml" not in manifest["files"]:
            raise BackupError("That backup has no profile, so there's nothing to restore.")
    apps = {PurePosixPath(rel).parts[:3] for rel in manifest["files"] if rel.startswith("applications/")
            and len(PurePosixPath(rel).parts) > 3}
    return Contents(manifest, len(apps))


def _relative(name: str) -> str:
    """The path inside the data folder for an entry `data/<path>`, refusing anything that could escape it."""
    p = PurePosixPath(name)
    if "\\" in name or p.is_absolute() or len(p.parts) < 2 or p.parts[0] != "data" \
            or any(part in ("", ".", "..") or ":" in part for part in p.parts) or p.parts[1] not in INCLUDE:
        raise BackupError("That backup is damaged or unsafe (it has a file outside the data folder).")
    return PurePosixPath(*p.parts[1:]).as_posix()


def restore(store, path: Path) -> dict:
    """Replace `store`'s data with the backup at `path`. The data it replaces is moved to
    `before-restore/<time>/` (nothing is deleted). Returns a summary for the user."""
    contents = inspect(path)
    private = store.private
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    staging = private / f".restore-{stamp}"
    oscompat.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(path) as z:
            root = staging.resolve()
            for rel, info in contents.manifest["files"].items():
                safe = _relative("data/" + rel)  # == rel (inspect), checked again where it's written
                data = z.read(f"data/{safe}")
                if not isinstance(info, dict) or _sha(data) != info.get("sha256"):
                    raise BackupError("That backup is damaged (a file doesn't match its checksum).")
                target = (staging / safe).resolve()
                if safe != rel or not target.is_relative_to(root):
                    raise BackupError("That backup is damaged or unsafe (it has a file outside the data folder).")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            keys = json.loads(z.read(KEYS)) if KEYS in z.namelist() else {}
        from .schema import load_profile
        try:
            load_profile(staging / "profile.yaml")
        except Exception as e:  # noqa: BLE001 — any reason: don't replace good data with a profile that won't load
            raise BackupError(f"The profile in that backup can't be read ({e}).") from e
        for sent in staging.glob("applications/*/*/sent/*/*"):
            sent.chmod(0o444)  # what was sent stays read-only, as when it was frozen
        kept = _swap(store, staging, private / KEPT / stamp)
    finally:
        oscompat.rmtree(staging, ignore_errors=True)
    restored_keys, failed_keys = _restore_keys(keys if isinstance(keys, dict) else {})
    store.migrate_layout()  # a backup made before a folder-layout change is brought up to date
    oscompat.make_private(private)
    return {**contents.summary, "kept": kept.relative_to(private).as_posix() if kept else None,
            "keys_restored": restored_keys, "keys_failed": failed_keys}


def _swap(store, staging: Path, kept: Path) -> Path | None:
    """Move the current data aside and the restored data in, all or nothing."""
    private = store.private
    with store.lock:
        moved_out, moved_in = [], []
        try:
            for top in INCLUDE:
                current = private / top
                if current.exists():
                    kept.mkdir(parents=True, exist_ok=True)
                    oscompat.replace(current, kept / top)
                    moved_out.append(top)
            for top in INCLUDE:
                if (staging / top).exists():
                    oscompat.replace(staging / top, private / top)
                    moved_in.append(top)
        except OSError as e:
            for top in moved_in:  # put everything back the way it was
                shutil.move(str(private / top), str(staging / top))
            for top in moved_out:
                shutil.move(str(kept / top), str(private / top))
            raise BackupError(f"Couldn't replace your data ({e}). Nothing was changed: close any open resume "
                              "files and try again.") from e
    return kept if moved_out else None


def _restore_keys(keys: dict) -> tuple[list[str], list[str]]:
    restored, failed = [], []
    for provider, key in keys.items():
        if provider not in apikey.PROVIDERS or not isinstance(key, str):
            continue
        try:
            apikey.save(key, provider)
            restored.append(provider)
        except (apikey.KeychainUnavailable, ValueError):
            failed.append(provider)
    return sorted(restored), sorted(failed)
