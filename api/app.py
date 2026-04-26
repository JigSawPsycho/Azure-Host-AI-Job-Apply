"""FastAPI app factory."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from db import init_db
from . import applications_routes, auth, runs, settings_routes

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="ai-apply", version="0.1.0")
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET is not set")
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax")

    init_db()

    app.include_router(auth.router)
    app.include_router(settings_routes.router)
    app.include_router(runs.router)
    app.include_router(applications_routes.router)

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app
