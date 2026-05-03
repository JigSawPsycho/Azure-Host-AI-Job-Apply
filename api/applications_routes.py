"""Applications listing/edit/mark-sent — port of scripts/apply-server.py."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import Application, ApplicationStatus, Job, User, get_session
from .auth import current_user

router = APIRouter(prefix="/api/applications", tags=["applications"])


class ApplicationCounts(BaseModel):
    unsent: int
    sent: int
    skipped: int


class ApplicationSummary(BaseModel):
    id: int
    job_id: int
    title: str
    company: str
    location: str
    url: str
    recommended_cv: str | None
    status: str
    sent_at: datetime | None


class ApplicationDetail(ApplicationSummary):
    body_md: str
    edited_body_md: str | None


class ApplicationUpdate(BaseModel):
    edited_body_md: str | None = None


def _summary(app: Application, job: Job) -> ApplicationSummary:
    raw = job.raw or {}
    return ApplicationSummary(
        id=app.id,
        job_id=job.id,
        title=raw.get("title", ""),
        company=raw.get("company", ""),
        location=raw.get("location", ""),
        url=raw.get("url", ""),
        recommended_cv=app.recommended_cv,
        status=app.status.value,
        sent_at=app.sent_at,
    )


@router.get("/counts", response_model=ApplicationCounts)
def application_counts(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ApplicationCounts:
    from sqlalchemy import func

    rows = (
        session.query(Application.status, func.count(Application.id))
        .join(Job, Application.job_id == Job.id)
        .filter(Job.user_id == user.id)
        .group_by(Application.status)
        .all()
    )
    counts = {s.value: 0 for s in ApplicationStatus}
    for status, n in rows:
        counts[status.value] = n
    return ApplicationCounts(**counts)


@router.get("", response_model=list[ApplicationSummary])
def list_applications(
    status: str = "unsent",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[ApplicationSummary]:
    try:
        target_status = ApplicationStatus(status)
    except ValueError:
        raise HTTPException(400, f"unknown status: {status}")
    rows = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.user_id == user.id, Application.status == target_status)
        .order_by(Application.id.desc())
        .all()
    )
    return [_summary(app, job) for app, job in rows]


@router.get("/{app_id}", response_model=ApplicationDetail)
def get_application(
    app_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    app, job = _resolve(session, app_id, user)
    base = _summary(app, job)
    return ApplicationDetail(**base.model_dump(), body_md=app.body_md, edited_body_md=app.edited_body_md)


@router.patch("/{app_id}", response_model=ApplicationDetail)
def update_application(
    app_id: int,
    payload: ApplicationUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    app, job = _resolve(session, app_id, user)
    if payload.edited_body_md is not None:
        app.edited_body_md = payload.edited_body_md
    session.commit()
    return get_application(app_id, user, session)


@router.post("/{app_id}/mark-sent", response_model=ApplicationDetail)
def mark_sent(
    app_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    app, _ = _resolve(session, app_id, user)
    app.status = ApplicationStatus.sent
    app.sent_at = datetime.now(timezone.utc)
    session.commit()
    return get_application(app_id, user, session)


@router.post("/{app_id}/skip", response_model=ApplicationDetail)
def skip(
    app_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    app, _ = _resolve(session, app_id, user)
    app.status = ApplicationStatus.skipped
    session.commit()
    return get_application(app_id, user, session)


def _resolve(session: Session, app_id: int, user: User) -> tuple[Application, Job]:
    row = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.id == app_id, Job.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "application not found")
    return row
