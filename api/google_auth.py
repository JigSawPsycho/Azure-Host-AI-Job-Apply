"""Google OIDC sign-in.

Mirrors the GitHub flow in api/auth.py. Returns 501 from /login when
GOOGLE_CLIENT_ID is unset, so the UI button surfaces a clear "not
configured yet" message rather than redirecting into a broken consent
screen.

Register at https://console.cloud.google.com/apis/credentials with:
  - Authorized redirect URI: <APP_URL>/auth/google/callback
  - Scopes: openid, email, profile
"""
from __future__ import annotations

import os
import secrets as _stdlib_secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import User
from db.session import SessionLocal
from .auth_common import find_or_create_user

router = APIRouter(prefix="/auth/google", tags=["auth"])

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)
SCOPES = "openid email profile"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    if not CLIENT_ID:
        raise HTTPException(
            501,
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in the environment.",
        )
    state = _stdlib_secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    url = (
        f"{AUTH_URL}"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES.replace(' ', '%20')}"
        f"&state={state}"
        f"&access_type=online"
        f"&prompt=select_account"
    )
    return RedirectResponse(url)


@router.get("/callback")
def callback(request: Request, code: str, state: str) -> RedirectResponse:
    if state != request.session.get("oauth_state"):
        raise HTTPException(400, "OAuth state mismatch")
    request.session.pop("oauth_state", None)

    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        userinfo_resp = client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_resp.raise_for_status()
        info = userinfo_resp.json()

    google_id = str(info["sub"])
    email = info.get("email")
    if not email:
        raise HTTPException(400, "Google did not return an email address")

    session: Session = SessionLocal()
    try:
        user, redirect = find_or_create_user(
            session, provider="google", email=email, google_id=google_id
        )
        if redirect is not None:
            return redirect
        session.commit()
        request.session["user_id"] = user.id
    finally:
        session.close()

    return RedirectResponse("/")
