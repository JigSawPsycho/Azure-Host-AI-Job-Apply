"""Environment helpers."""
from __future__ import annotations

import json
import logging
import os
import secrets as _stdlib_secrets
import stat
from pathlib import Path

log = logging.getLogger("ai-apply.env")

DEV_SECRETS_PATH = Path(__file__).resolve().parent.parent / "data" / ".dev-secrets.json"


def is_local() -> bool:
    """True for local dev. Used to gate OAuth providers + billing.

    Local mode = SECRETS_BACKEND != "azure-key-vault". Production sets
    SECRETS_BACKEND=azure-key-vault.
    """
    return os.environ.get("SECRETS_BACKEND", "local").lower() != "azure-key-vault"


def ensure_local_secrets() -> None:
    """Auto-generate + persist SESSION_SECRET and SECRETS_MASTER_KEY in local dev.

    No-op in prod or when both are already set in the environment. Generated
    values are written to data/.dev-secrets.json (gitignored) so sessions and
    encrypted user secrets survive restarts. Existing env vars always win.
    """
    if not is_local():
        return

    have_session = bool(os.environ.get("SESSION_SECRET"))
    have_master = bool(os.environ.get("SECRETS_MASTER_KEY"))
    if have_session and have_master:
        return

    DEV_SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if DEV_SECRETS_PATH.exists():
        try:
            data = json.loads(DEV_SECRETS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("dev secrets file unreadable, regenerating: %s", exc)
            data = {}

    changed = False
    if not have_session:
        if not data.get("SESSION_SECRET"):
            data["SESSION_SECRET"] = _stdlib_secrets.token_urlsafe(32)
            changed = True
        os.environ["SESSION_SECRET"] = data["SESSION_SECRET"]
        log.info("auto-generated SESSION_SECRET (local dev) at %s", DEV_SECRETS_PATH)

    if not have_master:
        if not data.get("SECRETS_MASTER_KEY"):
            from cryptography.fernet import Fernet
            data["SECRETS_MASTER_KEY"] = Fernet.generate_key().decode()
            changed = True
        os.environ["SECRETS_MASTER_KEY"] = data["SECRETS_MASTER_KEY"]
        log.info("auto-generated SECRETS_MASTER_KEY (local dev) at %s", DEV_SECRETS_PATH)

    if changed:
        DEV_SECRETS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            DEV_SECRETS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            # chmod is best-effort on Windows.
            pass
