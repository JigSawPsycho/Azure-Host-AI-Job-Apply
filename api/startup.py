"""Startup recovery hooks."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import Run, RunStatus
from db.session import SessionLocal

log = logging.getLogger(__name__)

_LIVE = (
    RunStatus.pending,
    RunStatus.scraping,
    RunStatus.fetching_cvs,
    RunStatus.generating,
)


def recover_orphaned_runs() -> None:
    """Mark any non-terminal Run as failed.

    Background tasks live in the api process. If the process dies mid-run,
    the Run row is left in a live status forever and POST /api/runs returns
    409. On every startup, sweep those rows: the worker that owned them is
    gone, so they're guaranteed dead.
    """
    session = SessionLocal()
    try:
        rows = session.query(Run).filter(Run.status.in_(_LIVE)).all()
        if not rows:
            return
        now = datetime.now(timezone.utc)
        for run in rows:
            run.status = RunStatus.failed
            run.finished_at = now
            run.error = "interrupted by server restart"
        session.commit()
        log.warning("recovered %d orphaned run(s)", len(rows))
    finally:
        session.close()
