"""API keys (Anthropic, OpenAI, OpenRouter), kept in the OS keychain (macOS Keychain, Windows Credential
Manager, Linux Secret Service) — never in the data folder and never sent to the browser. The provider's
environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY) is used when no key is stored."""

from __future__ import annotations

import os
from dataclasses import dataclass

SERVICE = "TailorbirdCV"
LEGACY_SERVICE = "AutoCV"  # the name before the rename: a key stored there moves to SERVICE the first time it's read


@dataclass(frozen=True)
class Provider:
    name: str      # shown to the user
    account: str   # keychain account under SERVICE
    env: str       # environment variable fallback
    prefix: str    # how its keys start (a hint, not enforced beyond a sanity check)


PROVIDERS = {
    "anthropic": Provider("Anthropic", "anthropic-api-key", "ANTHROPIC_API_KEY", "sk-ant-"),
    "openai": Provider("OpenAI", "openai-api-key", "OPENAI_API_KEY", "sk-"),
    "openrouter": Provider("OpenRouter", "openrouter-api-key", "OPENROUTER_API_KEY", "sk-or-"),
}
ACCOUNT = PROVIDERS["anthropic"].account  # kept for existing callers


class KeychainUnavailable(RuntimeError):
    pass


def _keyring():
    import keyring
    from keyring.errors import KeyringError
    return keyring, KeyringError


def _provider(provider: str) -> Provider:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown API provider: {provider}")
    return PROVIDERS[provider]


def get(provider: str = "anthropic") -> tuple[str | None, str | None]:
    """(key, where it came from: "keychain" | "environment" | None), or (None, "locked") when a keychain exists
    but reading it failed (locked, or access denied in the system prompt). Can block while the OS asks the user
    for permission: call it from a thread, never on the event loop."""
    p = _provider(provider)
    locked = False
    try:
        keyring, KeyringError = _keyring()
        stored = keyring.get_password(SERVICE, p.account) or _move_legacy(keyring, p.account)
    except Exception:  # noqa: BLE001
        stored, locked = None, backend_status()["available"]  # a real keychain that refused: not "no key"
    if stored:
        return stored, "keychain"
    if env := os.environ.get(p.env, "").strip():
        return env, "environment"
    return None, "locked" if locked else None


def _move_legacy(keyring, account: str) -> str | None:
    """A key saved under the old name: copied to SERVICE, then removed from the old entry (if that fails, it's
    simply read from there again next time)."""
    stored = keyring.get_password(LEGACY_SERVICE, account)
    if stored:
        keyring.set_password(SERVICE, account, stored)
        try:
            keyring.delete_password(LEGACY_SERVICE, account)
        except Exception:  # noqa: BLE001
            pass
    return stored


def save(key: str, provider: str = "anthropic") -> None:
    p = _provider(provider)
    key = key.strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        raise ValueError(f"That doesn't look like an {p.name} API key (they start with {p.prefix}).")
    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(SERVICE, p.account, key)
    except Exception as e:  # noqa: BLE001
        raise KeychainUnavailable(f"No system keychain is available to store the key. Set the {p.env} "
                                  "environment variable before starting TailorbirdCV instead.") from e


def delete(provider: str = "anthropic") -> None:
    p = _provider(provider)
    keyring, KeyringError = _keyring()
    for service in (SERVICE, LEGACY_SERVICE):  # never let a removed key come back from the old entry
        try:
            keyring.delete_password(service, p.account)
        except Exception:  # noqa: BLE001 — nothing stored
            pass


def backend_status() -> dict:
    """Whether a usable system keychain exists for storing keys: {available, backend}."""
    try:
        keyring, _ = _keyring()
        from keyring.backends import chainer, fail
        kr = keyring.get_keyring()
    except Exception:  # noqa: BLE001 — keyring missing or broken
        return {"available": False, "backend": None}
    name = type(kr).__name__
    module = type(kr).__module__
    if isinstance(kr, fail.Keyring) or (isinstance(kr, chainer.ChainerBackend) and not kr.backends) \
            or "null" in module.lower():
        return {"available": False, "backend": None}
    friendly = {"macOS": "macOS Keychain", "Windows": "Windows Credential Manager",
                "SecretService": "Secret Service", "kwallet": "KWallet"}
    label = next((v for k, v in friendly.items() if k.lower() in f"{module}.{name}".lower()), name)
    return {"available": True, "backend": label}


def masked(key: str | None) -> str | None:
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else None
