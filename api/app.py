"""FastAPI app factory."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from db import init_db
from .startup import recover_orphaned_runs
from . import (
    applications_routes,
    auth,
    email_auth,
    google_auth,
    runs,
    settings_routes,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="ai-apply", version="0.1.0")
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET is not set")
    https_only = os.environ.get("SESSION_HTTPS_ONLY", "0") == "1"
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        same_site="lax",
        https_only=https_only,
    )
    if os.environ.get("TRUST_PROXY_HEADERS", "0") == "1":
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    init_db()
    recover_orphaned_runs()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(google_auth.router)
    app.include_router(email_auth.router)
    app.include_router(settings_routes.router)
    app.include_router(runs.router)
    app.include_router(applications_routes.router)

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app
