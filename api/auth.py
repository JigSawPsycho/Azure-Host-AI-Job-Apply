"""GitHub OAuth flow.

Two distinct uses, single callback:

- **Sign in with GitHub** (anonymous user clicks the button on /login.html).
  Look up or create the User by github_id; set request.session["user_id"].

- **Connect GitHub** (already-signed-in user clicks Connect on /settings.html
  to authorize CV reads). The session already has user_id; attach the new
  token + github_id to that user without switching identity.

Scope is `read:user user:email repo` — enough to identify the user and read
CV files (including from private repos). Token is stored in the secret store;
only the ref hits the DB.
"""
from __future__ import annotations

import os
import secrets as _stdlib_secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import RepoLink, User, get_session
from .auth_common import find_or_create_user
from .secrets import get_store

router = APIRouter(prefix="/auth/github", tags=["auth"])

CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")
DEFAULT_SCOPES = "read:user user:email repo"


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    if not CLIENT_ID:
        raise HTTPException(500, "GITHUB_CLIENT_ID is not configured")
    state = _stdlib_secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    scope = DEFAULT_SCOPES
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scope.replace(' ', '%20')}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/callback")
def callback(
    request: Request,
    code: str,
    state: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if state != request.session.get("oauth_state"):
        raise HTTPException(400, "OAuth state mismatch")
    request.session.pop("oauth_state", None)

    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        user_resp = client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        )
        user_resp.raise_for_status()
        gh_user = user_resp.json()

        # Primary email may be private — gh_user["email"] is None in that
        # case. /user/emails (with user:email scope) returns all verified
        # addresses; pick the primary one.
        gh_email = gh_user.get("email")
        if not gh_email:
            emails_resp = client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            )
            if emails_resp.status_code == 200:
                emails = emails_resp.json()
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                gh_email = (primary or (emails[0] if emails else {})).get("email")

    existing_user_id = request.session.get("user_id")
    if existing_user_id:
        # Connect flow: attach the token + github identity to the
        # already-signed-in user (e.g. a user who signed up via Google
        # is now authorising GitHub access for CV reads). No provider
        # check here — the user is just linking GitHub for repo reads,
        # not switching their sign-in method.
        user = session.get(User, existing_user_id)
        if user is None:
            raise HTTPException(401, "session refers to a missing user")
        owner = (
            session.query(User)
            .filter(User.github_id == gh_user["id"], User.id != user.id)
            .one_or_none()
        )
        if owner is not None:
            user = owner
            existing_user_id = owner.id
        user.github_id = gh_user["id"]
        user.github_login = gh_user["login"]
        if gh_email and not user.email:
            user.email = gh_email
    else:
        if not gh_email:
            raise HTTPException(400, "GitHub did not return a verified email address")
        user, redirect = find_or_create_user(
            session,
            provider="github",
            email=gh_email,
            github_id=gh_user["id"],
            github_login=gh_user["login"],
        )
        if redirect is not None:
            return redirect

    store = get_store()
    if user.repo_link and user.repo_link.github_token_ref:
        store.delete(user.repo_link.github_token_ref)
    token_ref = store.put(f"github-token-{user.id}", access_token)

    if user.repo_link is None:
        user.repo_link = RepoLink(repo_full_name="", cv_dir="cv", github_token_ref=token_ref)
    else:
        user.repo_link.github_token_ref = token_ref

    session.commit()
    request.session["user_id"] = user.id
    # Connect flow lands on /settings.html; sign-in flow lands on /.
    return RedirectResponse("/settings.html" if existing_user_id else "/")


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "not signed in")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(401, "user not found")
    return user
