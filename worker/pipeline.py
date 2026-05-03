"""execute_run(run_id): the per-user worker pipeline.

Called from the FastAPI BackgroundTask in api/runs.py. In production
swap this for a Celery/RQ task; the function is deliberately
self-contained (no FastAPI types, opens its own DB session) so the swap
is mechanical.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.models_const import COST_BY_MODEL
from api.secrets import get_store
from api.token_ledger import debit_tokens
from db import (
    Application,
    ApplicationStatus,
    BillingMode,
    Criteria,
    Job,
    JobStatus,
    Run,
    RunStatus,
    TokenLedgerReason,
    UploadedCV,
    User,
)
from db.session import SessionLocal
from .extractors import CVFile
from .generate import GenerationError, generate_cover_letter
from .github_repo import GitHubClient
from .scrape import ScrapeError, scrape
from .scraper.models import SearchCriteria

log = logging.getLogger("ai-apply.worker")


def execute_run(run_id: int) -> None:
    session: Session = SessionLocal()
    try:
        _run(session, run_id)
    finally:
        session.close()


def _run(session: Session, run_id: int) -> None:
    run = session.get(Run, run_id)
    if run is None:
        log.error("run %s not found", run_id)
        return
    user = session.get(User, run.user_id)
    if user is None:
        _fail(session, run, "user missing")
        return

    uploaded = session.query(UploadedCV).filter_by(user_id=user.id).all()
    use_uploaded = len(uploaded) > 0

    store = get_store()
    try:
        github_token = (
            store.get(user.repo_link.github_token_ref)
            if (user.repo_link and user.repo_link.github_token_ref)
            else None
        )
    except Exception as exc:
        _fail(session, run, f"could not load secrets: {exc}")
        return
    if not use_uploaded:
        if not user.repo_link:
            _fail(session, run, "no uploaded CVs and no GitHub repo linked")
            return
        if not github_token:
            _fail(session, run, "github token missing")
            return

    # Pick the Anthropic key based on the user's billing mode. In tokens
    # mode we charge their balance and use the host's API key; in byok
    # mode we use the user's own key and don't touch the balance.
    billing_mode = user.billing_mode or BillingMode.tokens
    if billing_mode == BillingMode.byok:
        try:
            anthropic_key = store.get(user.anthropic_key_ref) if user.anthropic_key_ref else None
        except Exception as exc:
            _fail(session, run, f"could not load anthropic key: {exc}")
            return
        if not anthropic_key:
            _fail(session, run, "anthropic key missing (byok mode)")
            return
    else:
        anthropic_key = os.environ.get("ANTHROPIC_HOST_API_KEY")
        if not anthropic_key:
            _fail(session, run, "host billing not configured (ANTHROPIC_HOST_API_KEY missing)")
            return
        cost = COST_BY_MODEL.get(user.generation_model, 100)
        if (user.token_balance_centitokens or 0) < cost:
            _fail(session, run, "out of tokens — top up to keep generating")
            return

    criteria_rows = session.query(Criteria).filter_by(user_id=user.id, enabled=True).all()
    if not criteria_rows:
        _fail(session, run, "no enabled search criteria")
        return
    search_objs = [_to_search(c) for c in criteria_rows]

    seen_ids = {sid for (sid,) in session.query(Job.source_job_id).filter_by(user_id=user.id).all()}

    run.status = RunStatus.scraping
    session.commit()
    try:
        listings = scrape(search_objs, seen_job_ids=seen_ids)
    except ScrapeError as exc:
        _fail(session, run, f"scrape failed: {exc}")
        return

    listings = listings[: user.max_jobs_per_run]
    run.jobs_found = len(listings)
    session.commit()
    if not listings:
        _finish(session, run)
        return

    run.status = RunStatus.fetching_cvs
    session.commit()
    if use_uploaded:
        cvs = [CVFile(name=u.name, content=u.content, sha=u.sha) for u in uploaded]
    else:
        try:
            with GitHubClient(github_token, user.repo_link.repo_full_name) as gh:
                fetched = gh.list_cvs(user.repo_link.cv_dir)
        except Exception as exc:
            _fail(session, run, f"could not list CVs: {exc}")
            return
        if not fetched:
            _fail(session, run, f"no CV files found under {user.repo_link.cv_dir}")
            return
        cvs = [CVFile(name=f.name, content=f.content, sha=f.sha) for f in fetched]

    run.status = RunStatus.generating
    session.commit()
    generated = 0
    draft_cap = user.max_drafts_per_run
    cost = COST_BY_MODEL.get(user.generation_model, 100)
    for listing in listings:
        if generated >= draft_cap:
            break
        # Stop early if the user has run out of tokens (host-billed mode only).
        # The run still finishes cleanly — they can top up and start another.
        if billing_mode == BillingMode.tokens and (user.token_balance_centitokens or 0) < cost:
            log.info("run %s stopping early: out of tokens", run.id)
            break

        job = Job(
            user_id=user.id,
            source=listing.search if hasattr(listing, "search") else "",
            source_job_id=listing.jobId,
            raw=listing.to_dict(),
            status=JobStatus.new,
            scraped_at=datetime.now(timezone.utc),
        )
        # Source value comes from criteria.site, not search name — fix:
        job.source = _site_for(listing, criteria_rows)
        session.add(job)
        session.flush()

        try:
            result = generate_cover_letter(
                api_key=anthropic_key,
                model_id=user.generation_model,
                job=listing.to_dict(),
                cvs=cvs,
                language=listing.language or "en",
            )
        except GenerationError as exc:
            log.warning("generation failed for %s: %s", listing.jobId, exc)
            job.status = JobStatus.skipped
            session.commit()
            continue
        except Exception:
            log.exception("unexpected generation error for %s", listing.jobId)
            job.status = JobStatus.skipped
            session.commit()
            continue

        app = Application(
            job_id=job.id,
            kind="cover-letter",
            recommended_cv=result.chosen_cv,
            body_md=result.body_md,
            status=ApplicationStatus.unsent,
            generated_with_model=result.model_used,
        )
        session.add(app)
        session.flush()  # so we can reference app.id in the ledger entry

        if billing_mode == BillingMode.tokens:
            try:
                debit_tokens(
                    session,
                    user,
                    cost,
                    TokenLedgerReason.generation,
                    application_id=app.id,
                    model_id=result.model_used,
                )
            except ValueError:
                # Balance went negative between the pre-loop check and now (race
                # against another run, or admin debit). Roll back this letter.
                log.warning("run %s: balance exhausted mid-loop, dropping draft", run.id)
                session.rollback()
                break

        job.status = JobStatus.processed
        generated += 1
        run.applications_generated = generated
        session.commit()

    _finish(session, run)


def _to_search(c: Criteria) -> SearchCriteria:
    return SearchCriteria(
        name=c.name,
        keywords=c.keywords,
        site=c.site,
        location=c.location,
        work_arrangement=tuple(c.work_arrangement or ()),
        work_type=tuple(c.work_type or ()),
        salary_min=c.salary_min,
        exclude_keywords=tuple(c.exclude_keywords or ()),
    )


def _site_for(listing, criteria_rows: list[Criteria]) -> str:
    for c in criteria_rows:
        if c.name == listing.search:
            return c.site
    return ""


def _finish(session: Session, run: Run) -> None:
    run.status = RunStatus.finished
    run.finished_at = datetime.now(timezone.utc)
    session.commit()


def _fail(session: Session, run: Run, msg: str) -> None:
    run.status = RunStatus.failed
    run.error = msg
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    log.warning("run %s failed: %s", run.id, msg)
