"""The Anthropic API key, kept in the OS keychain (macOS Keychain, Windows Credential Manager,
Linux Secret Service) — never in the data folder and never sent to the browser.
ANTHROPIC_API_KEY in the environment is used when no key is stored."""

from __future__ import annotations

import os

SERVICE, ACCOUNT = "AutoCV", "anthropic-api-key"


class KeychainUnavailable(RuntimeError):
    pass


def _keyring():
    import keyring
    from keyring.errors import KeyringError
    return keyring, KeyringError


def get() -> tuple[str | None, str | None]:
    """(key, where it came from: "keychain" | "environment" | None)."""
    try:
        keyring, KeyringError = _keyring()
        stored = keyring.get_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001 — no usable keychain backend
        stored = None
    if stored:
        return stored, "keychain"
    if env := os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return env, "environment"
    return None, None


def save(key: str) -> None:
    key = key.strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        raise ValueError("That doesn't look like an Anthropic API key (they start with sk-ant-).")
    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(SERVICE, ACCOUNT, key)
    except Exception as e:  # noqa: BLE001
        raise KeychainUnavailable("No system keychain is available to store the key. Set the ANTHROPIC_API_KEY "
                                  "environment variable before starting AutoCV instead.") from e


def delete() -> None:
    keyring, KeyringError = _keyring()
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001 — nothing stored
        pass


def masked(key: str | None) -> str | None:
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else None
