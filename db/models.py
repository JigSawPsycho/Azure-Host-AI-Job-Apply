"""ORM models for ai-apply.

Mirrors the data-model sketch in the plan. Secrets are stored via the
secrets module (envelope-encrypted), not as plaintext columns.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    new = "new"
    processed = "processed"
    skipped = "skipped"


class ApplicationStatus(str, enum.Enum):
    unsent = "unsent"
    sent = "sent"
    skipped = "skipped"


class RunStatus(str, enum.Enum):
    pending = "pending"
    scraping = "scraping"
    fetching_cvs = "fetching_cvs"
    generating = "generating"
    finished = "finished"
    failed = "failed"


class BillingMode(str, enum.Enum):
    """How a user pays for cover-letter generation.

    - tokens: deduct from User.token_balance_centitokens; Anthropic calls
      use the host's ANTHROPIC_HOST_API_KEY.
    - byok: use the user's own anthropic_key_ref; no token deduction.
    """

    tokens = "tokens"
    byok = "byok"
    system = "system"


class TokenLedgerReason(str, enum.Enum):
    purchase = "purchase"
    generation = "generation"
    refund = "refund"
    admin_grant = "admin_grant"
    admin_debit = "admin_debit"


class TokenPurchaseStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    expired = "expired"
    failed = "failed"


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # All provider IDs are nullable: a user signs in with one of {GitHub,
    # Google, email/password (handled by the IdP your auth wiring uses)}.
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    github_login: Mapped[str | None] = mapped_column(String(80), nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    # Entra Object ID — set only on email/password signup. Lets us tell apart
    # an email-signup user (who later connects GitHub) from a github-signup user.
    entra_oid: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    # Email is canonical account ID; users sign up with exactly one provider
    # and must use that same provider for every subsequent login.
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    # Reference to a managed-secrets entry (e.g. Azure Key Vault secret name).
    # Never the raw key — see worker/secrets.py.
    anthropic_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The Anthropic model the user picked for generation. Internal only —
    # NEVER written into cover-letter bodies, PR descriptions, or any
    # artefact the employer can see.
    generation_model: Mapped[str] = mapped_column(String(80), default="claude-sonnet-4-6")

    # Per-run caps. max_jobs_per_run bounds how many listings the scraper
    # keeps; max_drafts_per_run bounds how many cover letters get generated
    # (and therefore how many Anthropic calls are billed) per run.
    max_jobs_per_run: Mapped[int] = mapped_column(Integer, default=25, server_default="25")
    max_drafts_per_run: Mapped[int] = mapped_column(Integer, default=25, server_default="25")

    # Billing. Tokens are stored as integer centitokens (×100) so 1.0 token = 100,
    # 0.25 = 25. Avoids float drift when crediting/debiting.
    billing_mode: Mapped[BillingMode] = mapped_column(
        Enum(BillingMode), default=BillingMode.tokens, server_default=BillingMode.tokens.value
    )
    token_balance_centitokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Per-user UI/feature settings (theme, default language, etc.).
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repo_link: Mapped["RepoLink | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    criteria: Mapped[list["Criteria"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    runs: Mapped[list["Run"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    token_ledger: Mapped[list["TokenLedgerEntry"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    token_purchases: Mapped[list["TokenPurchase"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    uploaded_cvs: Mapped[list["UploadedCV"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RepoLink(Base):
    __tablename__ = "repo_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), unique=True)
    repo_full_name: Mapped[str] = mapped_column(String(255))  # e.g. "octocat/cv"
    cv_dir: Mapped[str] = mapped_column(String(255), default="cv")
    # Reference to GitHub OAuth token in secret store, not raw token.
    github_token_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="repo_link")


class UploadedCV(Base):
    """User-uploaded CV / CLAUDE.md file stored directly in DB.

    Alternative to GitHub repo integration. When present, the worker
    pipeline reads from this table instead of fetching from GitHub.
    """

    __tablename__ = "uploaded_cv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="uploaded_cvs")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_uploaded_cv_user_name"),)


class Criteria(Base):
    """One row per saved search. Mirrors a single entry under
    `searches:` in the legacy `jobs/search-criteria.yml`."""

    __tablename__ = "criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    site: Mapped[str] = mapped_column(String(20))  # "au" | "nz" | "wanted"
    keywords: Mapped[str] = mapped_column(String(500), default="")
    location: Mapped[str] = mapped_column(String(120), default="All Australia")
    work_arrangement: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_type: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="criteria")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_criteria_user_name"),)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # "au" | "nz" | "wanted"
    source_job_id: Mapped[str] = mapped_column(String(120), index=True)
    raw: Mapped[dict] = mapped_column(JSON)  # full JobListing.to_dict()
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.new)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="jobs")
    application: Mapped["Application | None"] = relationship(back_populates="job", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_job_id", name="uq_job_user_source"),
    )


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="cover-letter")  # or "tailored-cv-ko" (v2)
    recommended_cv: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_md: Mapped[str] = mapped_column(Text)
    edited_body_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus), default=ApplicationStatus.unsent)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Internal metadata only — must never appear in body_md or any output
    # the employer sees. The generation prompt explicitly forbids the model
    # from naming itself or its provider.
    generated_with_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped[Job] = relationship(back_populates="application")


class Run(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.pending)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    applications_generated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="runs")


class TokenPurchase(Base):
    """One row per Stripe Checkout session.

    Created with status=pending when checkout starts; flipped to paid by
    the webhook handler, which also writes the matching credit ledger
    entry. The unique constraint on stripe_session_id makes the webhook
    idempotent — Stripe retries replayed events safely.
    """

    __tablename__ = "token_purchase"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    stripe_session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package_key: Mapped[str] = mapped_column(String(40))
    centitokens: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="usd")
    status: Mapped[TokenPurchaseStatus] = mapped_column(
        Enum(TokenPurchaseStatus), default=TokenPurchaseStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="token_purchases")


class TokenLedgerEntry(Base):
    """Immutable per-user audit trail of token movements.

    Every change to User.token_balance_centitokens has a matching row
    here. Reasons: purchase (+ from Stripe), generation (- per call),
    refund (+ from generation failure), admin_grant/admin_debit.
    """

    __tablename__ = "token_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    delta_centitokens: Mapped[int] = mapped_column(Integer)  # +credit / -debit
    balance_after_centitokens: Mapped[int] = mapped_column(Integer)
    reason: Mapped[TokenLedgerReason] = mapped_column(Enum(TokenLedgerReason))
    purchase_id: Mapped[int | None] = mapped_column(
        ForeignKey("token_purchase.id", ondelete="SET NULL"), nullable=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="token_ledger")
