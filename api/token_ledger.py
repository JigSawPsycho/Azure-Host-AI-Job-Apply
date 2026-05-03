"""Token credit/debit helpers.

Lives outside api/billing.py so the worker can import these without
pulling FastAPI routers in (which would create a circular import via
api.runs → worker.pipeline). Caller is responsible for committing.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db import TokenLedgerEntry, TokenLedgerReason, TokenPurchase, User


def credit_tokens(
    session: Session,
    user: User,
    centitokens: int,
    reason: TokenLedgerReason,
    *,
    purchase: TokenPurchase | None = None,
    note: str | None = None,
) -> TokenLedgerEntry:
    if centitokens <= 0:
        raise ValueError("credit_tokens expects a positive amount")
    user.token_balance_centitokens = (user.token_balance_centitokens or 0) + centitokens
    entry = TokenLedgerEntry(
        user_id=user.id,
        delta_centitokens=centitokens,
        balance_after_centitokens=user.token_balance_centitokens,
        reason=reason,
        purchase_id=purchase.id if purchase else None,
        note=note,
    )
    session.add(entry)
    return entry


def debit_tokens(
    session: Session,
    user: User,
    centitokens: int,
    reason: TokenLedgerReason,
    *,
    application_id: int | None = None,
    model_id: str | None = None,
    note: str | None = None,
) -> TokenLedgerEntry:
    if centitokens <= 0:
        raise ValueError("debit_tokens expects a positive amount")
    if (user.token_balance_centitokens or 0) < centitokens:
        raise ValueError(
            f"insufficient balance: have {user.token_balance_centitokens}, need {centitokens}"
        )
    user.token_balance_centitokens -= centitokens
    entry = TokenLedgerEntry(
        user_id=user.id,
        delta_centitokens=-centitokens,
        balance_after_centitokens=user.token_balance_centitokens,
        reason=reason,
        application_id=application_id,
        model_id=model_id,
        note=note,
    )
    session.add(entry)
    return entry
