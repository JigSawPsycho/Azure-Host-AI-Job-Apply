"""Settings endpoints: Anthropic API key, model choice, repo link, criteria."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import Criteria, User, get_session
from .auth import current_user
from .models_const import ALLOWED_MODEL_IDS, MODEL_OPTIONS
from .secrets import get_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ModelOptionOut(BaseModel):
    id: str
    label: str
    blurb: str


class SettingsOut(BaseModel):
    display_name: str
    github_login: str | None
    github_connected: bool
    has_anthropic_key: bool
    generation_model: str
    available_models: list[ModelOptionOut]
    repo_full_name: str
    cv_dir: str
    deliver_as_pr: bool


class SettingsUpdate(BaseModel):
    anthropic_key: str | None = None
    generation_model: str | None = None
    repo_full_name: str | None = None
    cv_dir: str | None = None
    deliver_as_pr: bool | None = None


class CriteriaIn(BaseModel):
    name: str
    site: str = Field(pattern="^(au|nz|wanted)$")
    keywords: str = ""
    location: str = "All Australia"
    work_arrangement: list[str] = Field(default_factory=list)
    work_type: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    exclude_keywords: list[str] = Field(default_factory=list)
    enabled: bool = True


class CriteriaOut(CriteriaIn):
    id: int


@router.get("", response_model=SettingsOut)
def read_settings(user: User = Depends(current_user)) -> SettingsOut:
    display_name = user.github_login or user.email or f"user-{user.id}"
    github_connected = bool(user.repo_link and user.repo_link.github_token_ref)
    return SettingsOut(
        display_name=display_name,
        github_login=user.github_login,
        github_connected=github_connected,
        has_anthropic_key=bool(user.anthropic_key_ref),
        generation_model=user.generation_model,
        available_models=[ModelOptionOut(**opt.__dict__) for opt in MODEL_OPTIONS],
        repo_full_name=user.repo_link.repo_full_name if user.repo_link else "",
        cv_dir=user.repo_link.cv_dir if user.repo_link else "cv",
        deliver_as_pr=user.repo_link.deliver_as_pr if user.repo_link else False,
    )


@router.put("", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> SettingsOut:
    store = get_store()

    if payload.anthropic_key is not None:
        if not payload.anthropic_key.startswith("sk-ant-"):
            raise HTTPException(400, "anthropic key must start with sk-ant-")
        if user.anthropic_key_ref:
            store.delete(user.anthropic_key_ref)
        user.anthropic_key_ref = store.put(f"anthropic-{user.id}", payload.anthropic_key)

    if payload.generation_model is not None:
        if payload.generation_model not in ALLOWED_MODEL_IDS:
            raise HTTPException(400, f"unknown model: {payload.generation_model}")
        user.generation_model = payload.generation_model

    repo_fields_set = any(
        v is not None for v in (payload.repo_full_name, payload.cv_dir, payload.deliver_as_pr)
    )
    if repo_fields_set and user.repo_link is None:
        # User signed in via Google/email and is trying to save a repo
        # name before connecting GitHub. Stash the values so they aren't
        # lost; the connect flow will fill in github_token_ref.
        from db import RepoLink

        user.repo_link = RepoLink(repo_full_name="", cv_dir="cv")
        session.add(user.repo_link)
        session.flush()

    if user.repo_link is not None:
        if payload.repo_full_name is not None:
            user.repo_link.repo_full_name = payload.repo_full_name
        if payload.cv_dir is not None:
            user.repo_link.cv_dir = payload.cv_dir
        if payload.deliver_as_pr is not None:
            user.repo_link.deliver_as_pr = payload.deliver_as_pr

    session.commit()
    return read_settings(user)


@router.get("/criteria", response_model=list[CriteriaOut])
def list_criteria(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[CriteriaOut]:
    rows = session.query(Criteria).filter_by(user_id=user.id).order_by(Criteria.id).all()
    return [CriteriaOut(id=r.id, **{k: getattr(r, k) for k in CriteriaIn.model_fields}) for r in rows]


@router.post("/criteria", response_model=CriteriaOut)
def create_criteria(
    payload: CriteriaIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CriteriaOut:
    row = Criteria(user_id=user.id, **payload.model_dump())
    session.add(row)
    session.commit()
    return CriteriaOut(id=row.id, **payload.model_dump())


@router.put("/criteria/{cid}", response_model=CriteriaOut)
def update_criteria(
    cid: int,
    payload: CriteriaIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CriteriaOut:
    row = session.query(Criteria).filter_by(id=cid, user_id=user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "criteria not found")
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    session.commit()
    return CriteriaOut(id=row.id, **payload.model_dump())


@router.delete("/criteria/{cid}")
def delete_criteria(
    cid: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    row = session.query(Criteria).filter_by(id=cid, user_id=user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "criteria not found")
    session.delete(row)
    session.commit()
    return {"ok": True}
