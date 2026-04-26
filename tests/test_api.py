"""Smoke tests for the API: anonymous → 401, login redirects, frontend serves."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_anonymous_settings_returns_401():
    assert _client().get("/api/settings").status_code == 401


def test_anonymous_applications_returns_401():
    assert _client().get("/api/applications").status_code == 401


def test_login_redirects_to_github():
    resp = _client().get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize")
    # Default scope: no `repo`.
    assert "repo" not in resp.headers["location"].split("scope=")[1].split("&")[0]


def test_login_with_pr_delivery_requests_repo_scope():
    resp = _client().get("/auth/github/login?deliver_as_pr=true", follow_redirects=False)
    assert resp.status_code == 307
    assert "repo" in resp.headers["location"]


def test_frontend_index_served():
    assert _client().get("/").status_code == 200


def test_static_css_served():
    assert _client().get("/static/apply.css").status_code == 200


def test_login_page_served():
    resp = _client().get("/login.html")
    assert resp.status_code == 200
    body = resp.text
    assert "Continue with Google" in body
    assert "Continue with GitHub" in body
    assert 'id="email-form"' in body


def test_signup_page_served():
    resp = _client().get("/signup.html")
    assert resp.status_code == 200


def test_email_login_returns_501_until_wired():
    resp = _client().post(
        "/auth/email/login",
        json={"email": "test@example.com", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 501
    assert "not wired up" in resp.json()["detail"].lower()


def test_email_signup_returns_501_until_wired():
    resp = _client().post(
        "/auth/email/signup",
        json={"email": "new@example.com", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 501


def test_google_login_returns_501_when_unconfigured(monkeypatch):
    # Default test env has no GOOGLE_CLIENT_ID — we expect a clear 501.
    monkeypatch.setattr("api.google_auth.CLIENT_ID", "")
    resp = _client().get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 501
    assert "not configured" in resp.json()["detail"].lower()


def test_google_login_redirects_when_configured(monkeypatch):
    monkeypatch.setattr("api.google_auth.CLIENT_ID", "test-google-id")
    resp = _client().get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-google-id" in location
    assert "openid" in location
