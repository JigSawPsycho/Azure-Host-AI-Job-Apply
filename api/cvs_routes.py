"""Direct CV / CLAUDE.md upload endpoints.

Lets users skip the GitHub integration and upload CV templates and
CLAUDE.md files directly. Storage is the `uploaded_cv` DB table.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import UploadedCV, User, get_session
from .auth import current_user

router = APIRouter(prefix="/api/cvs", tags=["cvs"])

_ALLOWED_EXTS = {".md", ".markdown", ".txt", ".pdf", ".docx"}
_MAX_FILE_BYTES = 250 * 1024  # 250 KB per file
_MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5 MB across all files per user


class UploadedCVOut(BaseModel):
    id: int
    name: str
    size: int
    sha: str
    uploaded_at: datetime


def _to_out(row: UploadedCV) -> UploadedCVOut:
    return UploadedCVOut(
        id=row.id,
        name=row.name,
        size=row.size,
        sha=row.sha,
        uploaded_at=row.uploaded_at,
    )


def _ext_ok(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _ALLOWED_EXTS)


@router.get("", response_model=list[UploadedCVOut])
def list_cvs(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[UploadedCVOut]:
    rows = (
        session.query(UploadedCV)
        .filter_by(user_id=user.id)
        .order_by(UploadedCV.name)
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=UploadedCVOut)
async def upload_cv(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> UploadedCVOut:
    name = (file.filename or "").strip()
    if not name:
        raise HTTPException(400, "filename required")
    # Strip any path components.
    name = name.replace("\\", "/").split("/")[-1]
    if not _ext_ok(name):
        raise HTTPException(
            400,
            f"unsupported file type — allowed: {', '.join(sorted(_ALLOWED_EXTS))}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            413, f"file too large (max {_MAX_FILE_BYTES // 1024} KB per file)"
        )

    existing = (
        session.query(UploadedCV)
        .filter_by(user_id=user.id, name=name)
        .one_or_none()
    )
    current_total = (
        session.query(func.coalesce(func.sum(UploadedCV.size), 0))
        .filter(UploadedCV.user_id == user.id)
        .scalar()
        or 0
    )
    existing_size = existing.size if existing is not None else 0
    projected_total = current_total - existing_size + len(content)
    if projected_total > _MAX_TOTAL_BYTES:
        raise HTTPException(
            413,
            f"total upload quota exceeded (max {_MAX_TOTAL_BYTES // (1024 * 1024)} MB across all files)",
        )

    sha = hashlib.sha1(content).hexdigest()
    if existing is not None:
        existing.content = content
        existing.sha = sha
        existing.size = len(content)
        row = existing
    else:
        row = UploadedCV(
            user_id=user.id,
            name=name,
            content=content,
            sha=sha,
            size=len(content),
        )
        session.add(row)
    session.commit()
    session.refresh(row)
    return _to_out(row)


@router.delete("/{cv_id}")
def delete_cv(
    cv_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    row = (
        session.query(UploadedCV)
        .filter_by(id=cv_id, user_id=user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "cv not found")
    session.delete(row)
    session.commit()
    return {"ok": True}
