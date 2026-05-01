"""Email + password sign-in via Microsoft Entra (auth code flow).

Single user flow handles both signup and signin — the Entra hosted page
collects credentials. We just redirect there and exchange the code on
callback. Mirrors the GitHub / Google flows in api/auth.py and
api/google_auth.py.

Required env (see .env.example):
  MS_TENANT_ID       — directory (tenant) ID
  MS_CLIENT_ID       — app registration client ID
  MS_CLIENT_SECRET   — app registration client secret value
  MS_REDIRECT_URI    — defaults to http://localhost:8000/auth/email/callback
  MS_AUTHORITY       — optional override. Default
                       https://login.microsoftonline.com/{MS_TENANT_ID}.
                       For External ID / B2C tenants, set this to the
                       full authority URL, e.g.
                       https://yourtenant.ciamlogin.com/{tenant_id}
"""
from __future__ import annotations

import base64
import json
import os
import secrets as _stdlib_secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import User
from db.session import SessionLocal

router = APIRouter(prefix="/auth/ms", tags=["auth"])

TENANT_ID = os.environ.get("MS_TENANT_ID", "")
CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get(
    "MS_REDIRECT_URI", "http://localhost:8000/auth/ms/callback"
)
AUTHORITY = os.environ.get(
    "MS_AUTHORITY", f"https://login.microsoftonline.com/{TENANT_ID}"
)
SCOPES = "openid email profile"


def _authorize_url(state: str, prompt: str | None = None) -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
    }
    if prompt:
        params["prompt"] = prompt
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def _require_config() -> None:
    if not (TENANT_ID and CLIENT_ID and CLIENT_SECRET):
        raise HTTPException(
            501,
            "Email sign-in is not configured. Set MS_TENANT_ID, "
            "MS_CLIENT_ID and MS_CLIENT_SECRET in the environment.",
        )


def _graph_lookup_email(oid: str) -> str | None:
    # Use a workforce-style authority for the Graph token regardless of
    # MS_AUTHORITY — Graph lives on login.microsoftonline.com even when
    # users authenticate against ciamlogin.com.
    graph_token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    with httpx.Client(timeout=10) as client:
        tok = client.post(
            graph_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        tok.raise_for_status()
        access = tok.json()["access_token"]

        resp = client.get(
            f"https://graph.microsoft.com/v1.0/users/{oid}",
            params={"$select": "mail,otherMails,identities,userPrincipalName"},
            headers={"Authorization": f"Bearer {access}"},
        )
        resp.raise_for_status()
        u = resp.json()

    for ident in u.get("identities", []):
        if ident.get("signInType") == "emailAddress" and ident.get("issuerAssignedId"):
            return ident["issuerAssignedId"]
    if u.get("mail"):
        return u["mail"]
    if u.get("otherMails"):
        return u["otherMails"][0]
    upn = u.get("userPrincipalName", "")
    return upn if "@" in upn and not upn.endswith(".onmicrosoft.com") else None


def _decode_id_token(id_token: str) -> dict:
    # Token came directly from Microsoft over TLS in this request, so we
    # trust the payload without re-verifying the signature. If this token
    # is ever forwarded from an untrusted source, switch to JWKS verify.
    _, payload_b64, _ = id_token.split(".")
    pad = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + pad))


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    _require_config()
    state = _stdlib_secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(_authorize_url(state))


@router.get("/signup")
def signup(request: Request) -> RedirectResponse:
    _require_config()
    state = _stdlib_secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    # Entra External ID honours prompt=create to land on the signup tab.
    # Workforce / B2C tenants ignore unknown prompts and fall back to
    # the default sign-in/up page, which is also fine.
    return RedirectResponse(_authorize_url(state, prompt="create"))


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(400, f"{error}: {error_description or ''}".strip(": "))
    if not code or not state:
        raise HTTPException(400, "Missing code/state in callback")
    if state != request.session.get("oauth_state"):
        raise HTTPException(400, "OAuth state mismatch")
    request.session.pop("oauth_state", None)

    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            f"{AUTHORITY}/oauth2/v2.0/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": SCOPES,
            },
        )
    if token_resp.status_code != 200:
        try:
            detail = token_resp.json().get("error_description", "token exchange failed")
        except Exception:
            detail = "token exchange failed"
        raise HTTPException(400, detail)

    claims = _decode_id_token(token_resp.json()["id_token"])
    # External ID emits "emails" (array); workforce emits "email" (string).
    # preferred_username is a fallback for tenants that omit both.
    emails = claims.get("emails")
    email = (
        (emails[0] if isinstance(emails, list) and emails else None)
        or claims.get("email")
        or claims.get("preferred_username")
    )
    if not email:
        # External ID local accounts: email lives in the user's identities
        # collection on Graph, not in the id_token. Fetch by oid using an
        # app-only token (requires User.Read.All application permission,
        # admin-consented).
        email = _graph_lookup_email(claims["oid"])
    if not email:
        raise HTTPException(
            400,
            f"Could not determine email. iss={claims.get('iss')!r} claims={sorted(claims.keys())}",
        )

    session: Session = SessionLocal()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email)
            session.add(user)
        session.commit()
        request.session["user_id"] = user.id
    finally:
        session.close()

    return RedirectResponse("/")
