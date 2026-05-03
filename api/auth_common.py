"""Shared sign-in helpers for the GitHub/Google/email auth flows.

Email is the canonical account ID. A user signs up under exactly one
provider and must use that same provider on every subsequent login.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import User


def _infer_provider(user: User) -> str:
    # GitHub is checked LAST: a user who signed up via Google/email may later
    # connect GitHub for repo reads, so github_id presence != signup provider.
    # entra_oid + google_id are signup-only markers, so we trust them first.
    if user.entra_oid is not None:
        return "email"
    if user.google_id is not None:
        return "google"
    if user.github_id is not None:
        return "github"
    return "email"


def provider_mismatch_redirect(expected: str, attempted: str, email: str) -> RedirectResponse:
    qs = urlencode({"error": "provider_mismatch", "expected": expected, "attempted": attempted, "email": email})
    return RedirectResponse(f"/login.html?{qs}")


def find_or_create_user(
    session: Session,
    *,
    provider: str,
    email: str,
    github_id: int | None = None,
    github_login: str | None = None,
    google_id: str | None = None,
    entra_oid: str | None = None,
) -> tuple[User | None, RedirectResponse | None]:
    """Look up by email and enforce provider match. Returns (user, redirect).

    On mismatch returns (None, redirect-to-login-with-error). On success
    returns (user, None) — caller is responsible for committing.
    """
    user = session.query(User).filter_by(email=email).one_or_none()
    if user is None:
        user = User(
            email=email,
            github_id=github_id,
            github_login=github_login,
            google_id=google_id,
            entra_oid=entra_oid,
        )
        session.add(user)
        session.flush()
        return user, None

    existing = _infer_provider(user)
    if existing != provider:
        return None, provider_mismatch_redirect(existing, provider, email)

    if provider == "github":
        user.github_id = github_id
        user.github_login = github_login
    elif provider == "google" and not user.google_id:
        user.google_id = google_id
    elif provider == "email" and not user.entra_oid and entra_oid:
        # Backfill: pre-migration email users had no entra_oid stored; set it
        # on their next email login so future inference is unambiguous.
        user.entra_oid = entra_oid
    return user, None
