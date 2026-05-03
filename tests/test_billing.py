"""Token billing + Stripe webhook smoke tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import current_user
from api.billing import _credit_for_session, credit_tokens, debit_tokens
from db import (
    BillingMode,
    TokenLedgerEntry,
    TokenLedgerReason,
    TokenPurchase,
    TokenPurchaseStatus,
    User,
)
from db.session import SessionLocal


def _make_user(**kwargs) -> int:
    s = SessionLocal()
    try:
        u = User(email=kwargs.pop("email", "t@example.com"), **kwargs)
        s.add(u)
        s.commit()
        return u.id
    finally:
        s.close()


def _signed_in_client(user_id: int) -> TestClient:
    app = create_app()

    def override():
        s = SessionLocal()
        try:
            yield s.get(User, user_id)
        finally:
            s.close()

    app.dependency_overrides[current_user] = override
    return TestClient(app)


def test_anonymous_billing_balance_returns_401():
    assert TestClient(create_app()).get("/api/billing/balance").status_code == 401


def test_default_user_is_in_tokens_mode_with_zero_balance():
    uid = _make_user(email="balance@example.com")
    resp = _signed_in_client(uid).get("/api/billing/balance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["billing_mode"] == "tokens"
    assert body["token_balance"] == 0.0
    assert body["token_balance_centitokens"] == 0
    # Three packages baked in.
    assert {p["key"] for p in body["packages"]} == {"starter", "standard", "bulk"}


def test_switching_to_byok_requires_api_key():
    uid = _make_user(email="byok@example.com")
    client = _signed_in_client(uid)
    resp = client.put("/api/billing/mode", json={"billing_mode": "byok"})
    assert resp.status_code == 400
    assert "anthropic" in resp.json()["detail"].lower()


def test_switching_to_byok_succeeds_when_key_set():
    uid = _make_user(email="byok-ok@example.com", anthropic_key_ref="local:fake")
    client = _signed_in_client(uid)
    resp = client.put("/api/billing/mode", json={"billing_mode": "byok"})
    assert resp.status_code == 200
    assert resp.json()["billing_mode"] == "byok"


def test_debit_tokens_writes_ledger_entry():
    uid = _make_user(email="debit@example.com", token_balance_centitokens=200)
    s = SessionLocal()
    try:
        user = s.get(User, uid)
        debit_tokens(s, user, 100, TokenLedgerReason.generation, model_id="claude-sonnet-4-6")
        s.commit()
        s.refresh(user)
        assert user.token_balance_centitokens == 100
        entries = s.query(TokenLedgerEntry).filter_by(user_id=uid).all()
        assert len(entries) == 1
        assert entries[0].delta_centitokens == -100
        assert entries[0].balance_after_centitokens == 100
        assert entries[0].reason == TokenLedgerReason.generation
        assert entries[0].model_id == "claude-sonnet-4-6"
    finally:
        s.close()


def test_debit_tokens_rejects_overdraft():
    uid = _make_user(email="overdraft@example.com", token_balance_centitokens=20)
    s = SessionLocal()
    try:
        user = s.get(User, uid)
        with pytest.raises(ValueError, match="insufficient balance"):
            debit_tokens(s, user, 100, TokenLedgerReason.generation)
    finally:
        s.close()


def test_credit_tokens_writes_positive_ledger_entry():
    uid = _make_user(email="credit@example.com")
    s = SessionLocal()
    try:
        user = s.get(User, uid)
        credit_tokens(s, user, 500, TokenLedgerReason.admin_grant, note="welcome bonus")
        s.commit()
        s.refresh(user)
        assert user.token_balance_centitokens == 500
        entry = s.query(TokenLedgerEntry).filter_by(user_id=uid).one()
        assert entry.delta_centitokens == 500
        assert entry.note == "welcome bonus"
    finally:
        s.close()


def test_webhook_credit_is_idempotent():
    """Stripe replays events. We must credit at most once per session."""
    uid = _make_user(email="webhook@example.com")
    s = SessionLocal()
    try:
        purchase = TokenPurchase(
            user_id=uid,
            stripe_session_id="cs_test_idempotent",
            package_key="standard",
            centitokens=5000,
            amount_cents=2000,
            currency="usd",
            status=TokenPurchaseStatus.pending,
        )
        s.add(purchase)
        s.commit()

        cs_event = {
            "id": "cs_test_idempotent",
            "payment_status": "paid",
            "payment_intent": "pi_test_xyz",
        }
        _credit_for_session(s, cs_event)
        _credit_for_session(s, cs_event)  # replay

        user = s.get(User, uid)
        assert user.token_balance_centitokens == 5000
        ledger = s.query(TokenLedgerEntry).filter_by(user_id=uid).all()
        assert len(ledger) == 1
        s.refresh(purchase)
        assert purchase.status == TokenPurchaseStatus.paid
        assert purchase.stripe_payment_intent_id == "pi_test_xyz"
    finally:
        s.close()


def test_webhook_skips_unpaid_session():
    uid = _make_user(email="unpaid@example.com")
    s = SessionLocal()
    try:
        s.add(
            TokenPurchase(
                user_id=uid,
                stripe_session_id="cs_test_unpaid",
                package_key="starter",
                centitokens=1000,
                amount_cents=500,
                currency="usd",
                status=TokenPurchaseStatus.pending,
            )
        )
        s.commit()
        _credit_for_session(s, {"id": "cs_test_unpaid", "payment_status": "unpaid"})
        user = s.get(User, uid)
        assert user.token_balance_centitokens == 0
    finally:
        s.close()


def test_start_run_returns_402_when_out_of_tokens(monkeypatch):
    """User in tokens mode with zero balance should be blocked at /api/runs."""
    from db import RepoLink

    uid = _make_user(email="poor@example.com")
    s = SessionLocal()
    try:
        user = s.get(User, uid)
        user.repo_link = RepoLink(repo_full_name="owner/repo", cv_dir="cv", github_token_ref="local:fake")
        s.add(user.repo_link)
        s.commit()
    finally:
        s.close()

    resp = _signed_in_client(uid).post("/api/runs")
    assert resp.status_code == 402
    assert "tokens" in resp.json()["detail"].lower()


def test_start_run_byok_mode_requires_anthropic_key():
    """User in byok mode with no api key should be blocked."""
    from db import RepoLink

    uid = _make_user(email="byok-norun@example.com", billing_mode=BillingMode.byok)
    s = SessionLocal()
    try:
        user = s.get(User, uid)
        user.repo_link = RepoLink(repo_full_name="owner/repo", cv_dir="cv", github_token_ref="local:fake")
        s.add(user.repo_link)
        s.commit()
    finally:
        s.close()

    resp = _signed_in_client(uid).post("/api/runs")
    assert resp.status_code == 400
    assert "anthropic" in resp.json()["detail"].lower()


def test_checkout_returns_501_when_stripe_unconfigured(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    uid = _make_user(email="nostripe@example.com")
    resp = _signed_in_client(uid).post("/api/billing/checkout", json={"package": "starter"})
    assert resp.status_code == 501


def test_checkout_rejects_unknown_package():
    uid = _make_user(email="badpkg@example.com")
    resp = _signed_in_client(uid).post("/api/billing/checkout", json={"package": "nope"})
    assert resp.status_code == 400


def test_settings_exposes_token_cost_per_model():
    """The model dropdown payload should carry per-model cost so the UI can
    show "1 token / letter" alongside each option."""
    uid = _make_user(email="costs@example.com")
    resp = _signed_in_client(uid).get("/api/settings")
    assert resp.status_code == 200
    by_id = {m["id"]: m for m in resp.json()["available_models"]}
    assert by_id["claude-haiku-4-5-20251001"]["cost_centitokens"] == 25
    assert by_id["claude-sonnet-4-6"]["cost_centitokens"] == 100
    assert by_id["claude-opus-4-7"]["cost_centitokens"] == 500
