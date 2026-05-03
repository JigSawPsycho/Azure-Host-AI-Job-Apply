"""POST /api/runs to kick off the worker pipeline. GET to poll status."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import BillingMode, Run, RunStatus, UploadedCV, User, get_session
from worker.pipeline import execute_run
from .auth import current_user
from .models_const import COST_BY_MODEL

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunOut(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    jobs_found: int
    applications_generated: int
    error: str | None


def _to_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        jobs_found=run.jobs_found,
        applications_generated=run.applications_generated,
        error=run.error,
    )


@router.post("", response_model=RunOut)
def start_run(
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> RunOut:
    billing_mode = user.billing_mode or BillingMode.tokens
    if billing_mode == BillingMode.byok:
        if not user.anthropic_key_ref:
            raise HTTPException(
                400, "set your Anthropic API key in settings first (bring-your-own-key mode)"
            )
    else:
        cost = COST_BY_MODEL.get(user.generation_model, 100)
        if (user.token_balance_centitokens or 0) < cost:
            raise HTTPException(
                402, "out of tokens — top up before starting a run, or switch to bring-your-own-key"
            )
    has_uploaded = (
        session.query(UploadedCV.id).filter_by(user_id=user.id).first() is not None
    )
    if not has_uploaded and (not user.repo_link or not user.repo_link.repo_full_name):
        raise HTTPException(
            400,
            "upload a CV directly, or connect a GitHub repo and pick a CV directory first",
        )
    in_progress = (
        session.query(Run.id)
        .filter_by(user_id=user.id)
        .filter(
            Run.status.in_(
                [
                    RunStatus.pending,
                    RunStatus.scraping,
                    RunStatus.fetching_cvs,
                    RunStatus.generating,
                ]
            )
        )
        .first()
    )
    if in_progress is not None:
        raise HTTPException(409, "a run is already in progress")

    run = Run(user_id=user.id, status=RunStatus.pending, started_at=datetime.now(timezone.utc))
    session.add(run)
    session.commit()
    session.refresh(run)

    background.add_task(execute_run, run.id)
    return _to_out(run)


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> RunOut:
    run = session.query(Run).filter_by(id=run_id, user_id=user.id).one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    return _to_out(run)


@router.get("", response_model=list[RunOut])
def list_runs(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[RunOut]:
    rows = session.query(Run).filter_by(user_id=user.id).order_by(Run.id.desc()).limit(20).all()
    return [_to_out(r) for r in rows]
