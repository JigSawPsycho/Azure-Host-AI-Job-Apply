"""Programmatic adapter around the vendored scrapers.

Replaces the filesystem-driven /scraper/run.py CLI with a function the
worker pipeline can call per user-run. Dedup against the per-user
seen-set comes from the DB rather than seen.json.
"""
from __future__ import annotations

from collections.abc import Iterable

import httpx

from .scraper.models import JobListing, SearchCriteria
from .scraper.seek import SeekClient
from .scraper.wanted import WantedClient

CLIENTS: dict[str, type] = {
    "au": SeekClient,
    "nz": SeekClient,
    "wanted": WantedClient,
}


class ScrapeError(RuntimeError):
    """A search or hydrate call failed; raised with the underlying httpx error."""


def scrape(
    criteria_list: list[SearchCriteria],
    seen_job_ids: Iterable[str],
    rejected_job_ids: Iterable[str] = (),
) -> list[JobListing]:
    """Run every search and return only jobs we haven't already seen.

    Caller is responsible for persisting the returned listings and
    extending the seen-set in the DB.
    """
    seen = set(seen_job_ids)
    rejected = set(rejected_job_ids)
    grouped: dict[type, list[SearchCriteria]] = {}
    for criteria in criteria_list:
        client_cls = CLIENTS.get(criteria.site)
        if client_cls is None:
            continue
        grouped.setdefault(client_cls, []).append(criteria)

    fresh: list[JobListing] = []
    failures: list[tuple[str, Exception]] = []
    for client_cls, group in grouped.items():
        with client_cls() as client:
            for criteria in group:
                try:
                    listings = client.search(criteria)
                except httpx.HTTPError as exc:
                    failures.append((criteria.name, exc))
                    continue
                new = [
                    listing
                    for listing in listings
                    if listing.jobId not in seen and listing.jobId not in rejected
                ]
                if not new:
                    continue
                try:
                    hydrated = client.hydrate(new)
                except httpx.HTTPError as exc:
                    failures.append((criteria.name, exc))
                    continue
                fresh.extend(hydrated)
                seen.update(listing.jobId for listing in hydrated)

    if failures and not fresh:
        # Surface the first error if every search failed; partial success returns what it has.
        name, err = failures[0]
        raise ScrapeError(f"search '{name}' failed: {err!r}") from err
    return fresh
