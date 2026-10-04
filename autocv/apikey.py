"""API keys (Anthropic, OpenAI, OpenRouter), kept in the OS keychain (macOS Keychain, Windows Credential
Manager, Linux Secret Service) — never in the data folder and never sent to the browser. The provider's
environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY) is used when no key is stored."""

from __future__ import annotations

import os
from dataclasses import dataclass

SERVICE = "AutoCV"


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
    """(key, where it came from: "keychain" | "environment" | None)."""
    p = _provider(provider)
    try:
        keyring, KeyringError = _keyring()
        stored = keyring.get_password(SERVICE, p.account)
    except Exception:  # noqa: BLE001 — no usable keychain backend
        stored = None
    if stored:
        return stored, "keychain"
    if env := os.environ.get(p.env, "").strip():
        return env, "environment"
    return None, None


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
                                  "environment variable before starting AutoCV instead.") from e


def delete(provider: str = "anthropic") -> None:
    p = _provider(provider)
    keyring, KeyringError = _keyring()
    try:
        keyring.delete_password(SERVICE, p.account)
    except Exception:  # noqa: BLE001 — nothing stored
        pass


def masked(key: str | None) -> str | None:
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else None
