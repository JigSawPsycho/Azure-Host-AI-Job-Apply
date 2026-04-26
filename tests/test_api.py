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
