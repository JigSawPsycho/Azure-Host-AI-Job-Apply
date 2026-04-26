"""Email + password endpoints — stubs for the UI to hit.

These deliberately return 501. Wire them up against your chosen
identity provider (Azure AD B2C / Entra External ID / etc.):

  - Verify credentials via the IdP (or local password_hash if you go
    self-hosted; in that case add the column to db/models.py:User and
    use bcrypt/argon2 — never plaintext).
  - Look up or create the User row by email.
  - Set request.session["user_id"] = user.id, then return 200.

The frontend POSTs JSON {email, password} and expects 200 to redirect
to "/", or a JSON error body {"detail": "…"} for inline status display.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/auth/email", tags=["auth"])


class EmailCredentials(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: EmailCredentials) -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "Email/password login is not wired up yet. Connect this endpoint "
            "to your identity provider (e.g. Azure AD B2C / Entra External ID)."
        ),
    )


@router.post("/signup")
def signup(payload: EmailCredentials) -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "Email/password signup is not wired up yet. Connect this endpoint "
            "to your identity provider (e.g. Azure AD B2C / Entra External ID)."
        ),
    )
