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
    """Create tables if they don't exist. Replace with Alembic migrations in prod."""
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
