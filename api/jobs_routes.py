"""Import job listings.

Accepts JSON conforming to the SelfMarketing scraper's `JobListing`
schema (see `worker/scraper/models.py`) and persists them as `Job` rows
ready for the generation pipeline. Mirrors the manual `jobs/inbox/*.json`
hand-off the SelfMarketing repo uses, but lands directly in the DB.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import Job, JobStatus, User, get_session
from .auth import current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobListingIn(BaseModel):
    """Mirror of `scraper.models.JobListing` — same field names so a file
    from SelfMarketing's `jobs/inbox/` can be POSTed unmodified."""

    jobId: str
    search: str = ""
    url: str
    title: str
    company: str
    location: str = ""
    work_arrangement: str = ""
    work_type: str = ""
    salary: str = ""
    posted_at: str = ""
    teaser: str = ""
    bullets: list[str] = Field(default_factory=list)
    description: str = ""
    language: str = "en"
    # Not present in the SelfMarketing JSON; lets the caller tag the
    # site explicitly. Falls back to URL/jobId inference.
    source: str | None = None


class ImportRequest(BaseModel):
    jobs: list[JobListingIn]


class ImportResultItem(BaseModel):
    jobId: str
    status: str  # "imported" | "duplicate"
    job_id: int | None = None


class ImportResult(BaseModel):
    imported: int
    duplicates: int
    items: list[ImportResultItem]


_SOURCE_BY_HOST = {
    "seek.com.au": "au",
    "www.seek.com.au": "au",
    "seek.co.nz": "nz",
    "www.seek.co.nz": "nz",
    "wanted.co.kr": "wanted",
    "www.wanted.co.kr": "wanted",
    "jumpit.saramin.co.kr": "jumpit",
}


def _infer_source(listing: JobListingIn) -> str:
    if listing.source:
        return listing.source
    if listing.jobId.startswith("wanted-"):
        return "wanted"
    if listing.jobId.startswith("jumpit-"):
        return "jumpit"
    host = urlparse(listing.url).netloc.lower()
    return _SOURCE_BY_HOST.get(host, "import")


def _raw_payload(listing: JobListingIn) -> dict[str, Any]:
    raw = listing.model_dump()
    raw.pop("source", None)
    return raw


def _perform_import(
    listings: list[JobListingIn], user: User, session: Session
) -> ImportResult:
    items: list[ImportResultItem] = []
    imported = 0
    duplicates = 0
    now = datetime.now(timezone.utc)
    for listing in listings:
        source = _infer_source(listing)
        existing = (
            session.query(Job)
            .filter_by(
                user_id=user.id,
                source=source,
                source_job_id=listing.jobId,
            )
            .one_or_none()
        )
        if existing is not None:
            items.append(
                ImportResultItem(
                    jobId=listing.jobId, status="duplicate", job_id=existing.id
                )
            )
            duplicates += 1
            continue
        job = Job(
            user_id=user.id,
            source=source,
            source_job_id=listing.jobId,
            raw=_raw_payload(listing),
            status=JobStatus.new,
            scraped_at=now,
        )
        session.add(job)
        session.flush()
        items.append(
            ImportResultItem(jobId=listing.jobId, status="imported", job_id=job.id)
        )
        imported += 1
    session.commit()
    return ImportResult(imported=imported, duplicates=duplicates, items=items)


@router.post("/import", response_model=ImportResult)
def import_jobs(
    payload: ImportRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ImportResult:
    if not payload.jobs:
        raise HTTPException(400, "no jobs supplied")
    return _perform_import(payload.jobs, user, session)


@router.post("/import-file", response_model=ImportResult)
async def import_jobs_file(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ImportResult:
    """Upload a single JobListing JSON or an array of them.

    Same shape as files in SelfMarketing's `jobs/inbox/` directory.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"invalid JSON: {exc}")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise HTTPException(400, "expected a JobListing object or array of objects")
    try:
        listings = [JobListingIn.model_validate(item) for item in data]
    except Exception as exc:
        raise HTTPException(400, f"invalid listing payload: {exc}")
    if not listings:
        raise HTTPException(400, "no jobs supplied")
    return _perform_import(listings, user, session)
