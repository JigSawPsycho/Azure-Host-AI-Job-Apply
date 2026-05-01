"""SQLAlchemy engine + session factory.

DATABASE_URL defaults to a local SQLite file under ./data/ for dev. Set
to a Postgres URL in production (Azure Database for PostgreSQL).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_SQLITE = "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data" / "ai-apply.db")
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)

if DATABASE_URL.startswith("sqlite"):
    Path(DEFAULT_SQLITE.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they don't exist. Replace with Alembic migrations in prod.

    Uses a Postgres advisory lock to serialise concurrent boots — gunicorn
    --preload already runs this once per master, but multi-instance App
    Service scale-out can race two containers on the same DB.
    """
    from sqlalchemy.exc import IntegrityError, ProgrammingError
    from sqlalchemy import text

    if engine.dialect.name == "postgresql":
        # Advisory lock serialises concurrent boots. Outside the lock we
        # also swallow IntegrityError/ProgrammingError on CREATE TYPE
        # because SQLAlchemy's checkfirst doesn't reliably see existing
        # ENUM types in pg_type across reconnections.
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_lock(91237501)"))
        try:
            Base.metadata.create_all(engine)
        except (IntegrityError, ProgrammingError):
            pass
        finally:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_unlock(91237501)"))
    else:
        Base.metadata.create_all(engine)
    _ensure_user_columns()


def _ensure_user_columns() -> None:
    """Tiny in-place migration: add columns introduced after initial deploy.

    Real prod uses Alembic; this keeps the dev SQLite db usable without
    forcing a wipe each time a column is added.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "user" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("user")}
    additions = {
        "max_jobs_per_run": "INTEGER NOT NULL DEFAULT 25",
        "max_drafts_per_run": "INTEGER NOT NULL DEFAULT 25",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {name} {ddl}'))


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
