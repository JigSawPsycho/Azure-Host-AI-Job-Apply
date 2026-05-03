"""Stripe-backed token billing.

Endpoints (all under /api/billing):

- GET  /balance          → current balance + mode + package catalogue
- POST /mode             → switch billing_mode between "tokens" and "byok"
- POST /checkout         → create a Stripe Checkout Session, return its URL
- POST /webhook          → Stripe webhook (verifies signature, credits tokens)
- GET  /ledger           → recent token movements for the signed-in user

Webhook contract: we listen for `checkout.session.completed`. Idempotency
is provided by the unique constraint on TokenPurchase.stripe_session_id —
replays from Stripe (or our own retries) are no-ops.

For local dev without Stripe configured, /checkout returns 501 so the UI
can show a clean "billing not configured" message.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import (
    BillingMode,
    TokenLedgerEntry,
    TokenLedgerReason,
    TokenPurchase,
    TokenPurchaseStatus,
    User,
    get_session,
)
from .auth import current_user
from .models_const import (
    PACKAGES_BY_KEY,
    TOKEN_PACKAGES,
    centitokens_to_tokens,
)
from .token_ledger import credit_tokens, debit_tokens  # noqa: F401  (re-export)

log = logging.getLogger("ai-apply.billing")

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _stripe():
    """Lazy import + configure. Returns None if not configured."""
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    import stripe  # type: ignore[import-not-found]

    stripe.api_key = key
    return stripe


def _success_url() -> str:
    return os.environ.get(
        "STRIPE_SUCCESS_URL",
        "http://localhost:8000/settings.html?billing=success&session_id={CHECKOUT_SESSION_ID}",
    )


def _cancel_url() -> str:
    return os.environ.get(
        "STRIPE_CANCEL_URL", "http://localhost:8000/settings.html?billing=cancelled"
    )


# ─── Schemas ──────────────────────────────────────────────────────────


class PackageOut(BaseModel):
    key: str
    label: str
    tokens: float
    amount_cents: int
    blurb: str


class BalanceOut(BaseModel):
    billing_mode: str
    token_balance: float
    token_balance_centitokens: int
    has_anthropic_key: bool
    host_billing_available: bool
    packages: list[PackageOut]


class ModeUpdate(BaseModel):
    billing_mode: str = Field(pattern="^(tokens|byok)$")


class CheckoutIn(BaseModel):
    package: str


class CheckoutOut(BaseModel):
    url: str
    session_id: str


class LedgerEntryOut(BaseModel):
    id: int
    delta_centitokens: int
    delta_tokens: float
    balance_after_tokens: float
    reason: str
    model_id: str | None
    note: str | None
    created_at: datetime


def _packages_payload() -> list[PackageOut]:
    return [
        PackageOut(
            key=p.key,
            label=p.label,
            tokens=centitokens_to_tokens(p.centitokens),
            amount_cents=p.amount_cents,
            blurb=p.blurb,
        )
        for p in TOKEN_PACKAGES
    ]


# ─── Routes ───────────────────────────────────────────────────────────


@router.get("/balance", response_model=BalanceOut)
def get_balance(user: User = Depends(current_user)) -> BalanceOut:
    return BalanceOut(
        billing_mode=user.billing_mode.value if user.billing_mode else BillingMode.tokens.value,
        token_balance=centitokens_to_tokens(user.token_balance_centitokens or 0),
        token_balance_centitokens=user.token_balance_centitokens or 0,
        has_anthropic_key=bool(user.anthropic_key_ref),
        host_billing_available=bool(os.environ.get("ANTHROPIC_HOST_API_KEY")),
        packages=_packages_payload(),
    )


@router.put("/mode", response_model=BalanceOut)
def set_mode(
    payload: ModeUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> BalanceOut:
    if payload.billing_mode == BillingMode.byok.value and not user.anthropic_key_ref:
        raise HTTPException(
            400,
            "set your Anthropic API key in settings before switching to bring-your-own-key mode",
        )
    user.billing_mode = BillingMode(payload.billing_mode)
    session.commit()
    return get_balance(user)


@router.post("/checkout", response_model=CheckoutOut)
def start_checkout(
    payload: CheckoutIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CheckoutOut:
    pkg = PACKAGES_BY_KEY.get(payload.package)
    if pkg is None:
        raise HTTPException(400, f"unknown package: {payload.package}")
    stripe = _stripe()
    if stripe is None:
        raise HTTPException(501, "Stripe is not configured (STRIPE_SECRET_KEY missing)")

    customer_id = user.stripe_customer_id
    if not customer_id:
        cust = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user.id)},
        )
        customer_id = cust["id"]
        user.stripe_customer_id = customer_id

    cs = stripe.checkout.Session.create(
        mode="payment",
        customer=customer_id,
        success_url=_success_url(),
        cancel_url=_cancel_url(),
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": pkg.amount_cents,
                    "product_data": {
                        "name": f"{pkg.label} — {centitokens_to_tokens(pkg.centitokens)} tokens",
                        "description": pkg.blurb,
                    },
                },
            }
        ],
        metadata={
            "user_id": str(user.id),
            "package_key": pkg.key,
            "centitokens": str(pkg.centitokens),
        },
    )

    purchase = TokenPurchase(
        user_id=user.id,
        stripe_session_id=cs["id"],
        package_key=pkg.key,
        centitokens=pkg.centitokens,
        amount_cents=pkg.amount_cents,
        currency="usd",
        status=TokenPurchaseStatus.pending,
    )
    session.add(purchase)
    session.commit()
    return CheckoutOut(url=cs["url"], session_id=cs["id"])


@router.post("/webhook")
async def stripe_webhook(
    request: Request, session: Session = Depends(get_session)
) -> dict:
    """Stripe → us. Verify signature, then credit tokens on payment success.

    Idempotent: we look up by stripe_session_id and skip if already paid.
    """
    stripe = _stripe()
    if stripe is None:
        raise HTTPException(501, "Stripe is not configured")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(501, "STRIPE_WEBHOOK_SECRET is not configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception as exc:
        log.warning("invalid stripe signature: %s", exc)
        raise HTTPException(400, "invalid signature")

    if event["type"] == "checkout.session.completed":
        cs = event["data"]["object"]
        _credit_for_session(session, cs)

    return {"received": True}


def _credit_for_session(session: Session, cs: dict) -> None:
    """Apply a completed Checkout session to the matching TokenPurchase."""
    session_id = cs.get("id")
    if not session_id:
        return
    purchase = (
        session.query(TokenPurchase).filter_by(stripe_session_id=session_id).one_or_none()
    )
    if purchase is None:
        log.warning("webhook for unknown session %s", session_id)
        return
    if purchase.status == TokenPurchaseStatus.paid:
        return  # already credited; replay is a no-op
    if cs.get("payment_status") != "paid":
        return  # only credit on actual payment

    user = session.get(User, purchase.user_id)
    if user is None:
        log.warning("purchase %s references missing user", purchase.id)
        return

    purchase.status = TokenPurchaseStatus.paid
    purchase.paid_at = datetime.now(timezone.utc)
    purchase.stripe_payment_intent_id = cs.get("payment_intent")
    session.flush()  # so credit_tokens can reference purchase.id

    credit_tokens(
        session,
        user,
        purchase.centitokens,
        TokenLedgerReason.purchase,
        purchase=purchase,
        note=f"package={purchase.package_key}",
    )
    session.commit()


@router.get("/ledger", response_model=list[LedgerEntryOut])
def list_ledger(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    limit: int = 50,
) -> list[LedgerEntryOut]:
    rows = (
        session.query(TokenLedgerEntry)
        .filter_by(user_id=user.id)
        .order_by(TokenLedgerEntry.id.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        LedgerEntryOut(
            id=r.id,
            delta_centitokens=r.delta_centitokens,
            delta_tokens=centitokens_to_tokens(r.delta_centitokens),
            balance_after_tokens=centitokens_to_tokens(r.balance_after_centitokens),
            reason=r.reason.value,
            model_id=r.model_id,
            note=r.note,
            created_at=r.created_at,
        )
        for r in rows
    ]
