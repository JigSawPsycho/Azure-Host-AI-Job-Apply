"""Dataclasses describing scraped jobs and search configuration."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class SearchCriteria:
    name: str
    keywords: str
    site: str = "au"
    location: str = "All Australia"
    work_arrangement: tuple[str, ...] = ()
    work_type: tuple[str, ...] = ()
    salary_min: int | None = None
    exclude_keywords: tuple[str, ...] = ()

    ALLOWED_SITES = ("au", "nz", "wanted")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SearchCriteria":
        site = str(raw.get("site", "au")).lower()
        if site not in cls.ALLOWED_SITES:
            raise ValueError(
                f"site must be one of {cls.ALLOWED_SITES}, got {site!r}"
            )
        return cls(
            name=str(raw["name"]),
            keywords=str(raw.get("keywords", "")),
            site=site,
            location=str(raw.get("location", "All Australia")),
            work_arrangement=tuple(raw.get("work_arrangement") or ()),
            work_type=tuple(raw.get("work_type") or ()),
            salary_min=raw.get("salary_min"),
            exclude_keywords=tuple(raw.get("exclude_keywords") or ()),
        )


@dataclass
class JobListing:
    jobId: str
    search: str
    url: str
    title: str
    company: str
    location: str
    work_arrangement: str = ""
    work_type: str = ""
    salary: str = ""
    posted_at: str = ""
    teaser: str = ""
    bullets: list[str] = field(default_factory=list)
    description: str = ""
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def slug(self) -> str:
        parts = f"{self.company}-{self.title}".lower()
        safe = []
        for ch in parts:
            if ch.isalnum():
                safe.append(ch)
            elif safe and safe[-1] != "-":
                safe.append("-")
        slug = "".join(safe).strip("-")
        return slug[:80] or "job"

    def filename(self) -> str:
        return f"{self.jobId}-{self.slug()}.json"
