"""API key and endpoint. Order: TYPESAFE_API_KEY env var, then macOS Keychain
(service typesafe-jev-api-key, account jev-opportunity-atlas). The key is returned to
the caller only; it is never logged or stored."""

import os
import subprocess

SERVICE, ACCOUNT = "typesafe-jev-api-key", "jev-opportunity-atlas"


class MissingKey(RuntimeError):
    pass


def _keychain() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def get_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY") or _keychain()
    if not key:
        raise MissingKey(
            f"No Jev key: set TYPESAFE_API_KEY or add Keychain item {SERVICE}/{ACCOUNT}"
        )
    return key


def base_url() -> str:
    return os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
