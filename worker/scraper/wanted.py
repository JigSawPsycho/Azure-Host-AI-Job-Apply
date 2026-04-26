"""Wanted (wanted.co.kr) search and detail-page fetcher.

Keyword search hits /api/chaos/search/v1/results with a plain-string `query`
param; the API treats multi-word values as exact phrases, so WantedClient.search
tokenises on whitespace and unions per-term results. Detail pulls from
/api/chaos/jobs/v4/{id}/details (response shape: data.job.detail) with an HTML
fallback via the embedded __NEXT_DATA__ script tag on /wd/{id}. If Wanted
changes the endpoint shape or starts blocking requests, SITE_CONFIG and the
two parse functions are the swap points.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from .models import JobListing, SearchCriteria

SITE_CONFIG = {
    "search_url": "https://www.wanted.co.kr/api/chaos/search/v1/results",
    "detail_api_url": "https://www.wanted.co.kr/api/chaos/jobs/v4/{job_id}/details",
    "detail_page_url": "https://www.wanted.co.kr/wd/{job_id}",
    "country": "kr",
    "job_sort": "job.latest_order",
    "locations": "all",
    "search_tab": "position",
    "limit": 20,
    "id_prefix": "wanted-",
    "hydrate_delay_s": 1.0,
    "hosts": ("www.wanted.co.kr", "wanted.co.kr"),
}

LISTING_PATH_RE = re.compile(r"/wd/(\d+)")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.wanted.co.kr/",
}

SECTION_HEADINGS = [
    ("intro", "소개"),
    ("main_tasks", "주요 업무"),
    ("requirements", "자격 요건"),
    ("preferred_points", "우대 사항"),
    ("benefits", "혜택 및 복지"),
]


def build_search_params(criteria: SearchCriteria, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {
        "country": SITE_CONFIG["country"],
        "job_sort": SITE_CONFIG["job_sort"],
        "locations": SITE_CONFIG["locations"],
        "tab": SITE_CONFIG["search_tab"],
        "limit": SITE_CONFIG["limit"],
        "offset": (page - 1) * SITE_CONFIG["limit"],
    }
    if criteria.keywords:
        params["query"] = criteria.keywords
    if criteria.salary_min:
        params["annual_pay_gte"] = int(criteria.salary_min)
    return params


def _strip_prefix(job_id: str) -> str:
    prefix = SITE_CONFIG["id_prefix"]
    return job_id[len(prefix):] if job_id.startswith(prefix) else job_id


def parse_search_response(payload: dict[str, Any], criteria: SearchCriteria) -> list[JobListing]:
    listings: list[JobListing] = []
    positions = payload.get("positions")
    if isinstance(positions, dict):
        data: Any = positions.get("data") or []
    else:
        data = payload.get("data") or payload.get("results") or []
    if isinstance(data, dict):
        data = data.get("jobs") or data.get("items") or []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or item.get("job_id") or "").strip()
        if not raw_id:
            continue

        position = item.get("position") or item.get("name") or ""
        title = str(position).strip()
        company = (
            (item.get("company") or {}).get("name")
            if isinstance(item.get("company"), dict)
            else item.get("company_name")
        ) or ""
        company = str(company).strip()

        teaser = str(item.get("intro") or item.get("summary") or "").strip()
        haystack = " ".join([title, company, teaser]).lower()
        if any(bad.lower() in haystack for bad in criteria.exclude_keywords):
            continue

        bullets: list[str] = []
        for tag in item.get("skill_tags") or item.get("tags") or []:
            if isinstance(tag, dict):
                label = tag.get("title") or tag.get("name") or ""
            else:
                label = str(tag)
            label = str(label).strip()
            if label:
                bullets.append(label)

        location = ""
        address = item.get("address")
        if isinstance(address, dict):
            location = str(address.get("location") or address.get("full_location") or "").strip()
        if not location:
            locs = item.get("locations") or []
            if isinstance(locs, list) and locs:
                first = locs[0]
                if isinstance(first, dict):
                    location = str(first.get("name") or first.get("label") or "").strip()
                else:
                    location = str(first).strip()

        posted_at = str(item.get("confirm_time") or item.get("listing_start_time") or "")[:10]

        salary = ""
        pay = item.get("annual_pay") or item.get("salary")
        if isinstance(pay, dict):
            low = pay.get("gte") or pay.get("min")
            high = pay.get("lte") or pay.get("max")
            if low or high:
                salary = f"{low or ''}-{high or ''}".strip("-")
        elif pay:
            salary = str(pay).strip()

        job_id = f"{SITE_CONFIG['id_prefix']}{raw_id}"
        listings.append(
            JobListing(
                jobId=job_id,
                search=criteria.name,
                url=SITE_CONFIG["detail_page_url"].format(job_id=raw_id),
                title=title,
                company=company,
                location=location,
                work_arrangement="",
                work_type="",
                salary=salary,
                posted_at=posted_at,
                teaser=teaser,
                bullets=bullets,
                language="ko",
            )
        )
    return listings


def _join_sections(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, heading in SECTION_HEADINGS:
        value = detail.get(key) or ""
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        value = str(value).strip()
        if value:
            parts.append(f"## {heading}\n{value}")
    return "\n\n".join(parts)


def parse_detail_json(payload: dict[str, Any]) -> str:
    data = payload.get("data") or payload
    if isinstance(data, dict):
        job = data.get("job") or data
        if isinstance(job, dict):
            detail = job.get("detail") or job
            if isinstance(detail, dict):
                body = _join_sections(detail)
                if body:
                    return body
    return ""


def parse_listing_url(url: str) -> str:
    """Return the raw numeric job id from a Wanted detail URL.

    Raises ValueError if the host or path doesn't match a Wanted listing.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in SITE_CONFIG["hosts"]:
        raise ValueError(f"Unsupported Wanted host: {host!r}")
    match = LISTING_PATH_RE.search(parsed.path or "")
    if not match:
        raise ValueError(f"Could not extract Wanted job id from {url!r}")
    return match.group(1)


def _detail_address(detail_or_job: dict[str, Any]) -> str:
    address = detail_or_job.get("address")
    if isinstance(address, dict):
        return str(
            address.get("location") or address.get("full_location") or ""
        ).strip()
    return ""


def parse_detail_listing_json(
    payload: dict[str, Any], raw_id: str, search_name: str
) -> JobListing:
    data = payload.get("data") or payload
    job: dict[str, Any] = data.get("job") if isinstance(data, dict) else {}
    if not isinstance(job, dict):
        job = {}
    detail = job.get("detail") if isinstance(job.get("detail"), dict) else {}

    title = str(
        (detail.get("position") if isinstance(detail, dict) else None)
        or job.get("position")
        or ""
    ).strip()

    company_obj = job.get("company") or {}
    if isinstance(company_obj, dict):
        company = str(company_obj.get("name") or "").strip()
    else:
        company = str(company_obj or "").strip()

    location = _detail_address(job)
    if not location and isinstance(detail, dict):
        location = _detail_address(detail)

    posted_at = str(
        job.get("confirm_time")
        or job.get("listing_start_time")
        or (detail.get("confirm_time") if isinstance(detail, dict) else "")
        or ""
    )[:10]

    description = _join_sections(detail) if isinstance(detail, dict) else ""

    return JobListing(
        jobId=f"{SITE_CONFIG['id_prefix']}{raw_id}",
        search=search_name,
        url=SITE_CONFIG["detail_page_url"].format(job_id=raw_id),
        title=title,
        company=company,
        location=location,
        work_arrangement="",
        work_type="",
        salary="",
        posted_at=posted_at,
        teaser="",
        bullets=[],
        description=description,
        language="ko",
    )


def parse_detail_html(html: str) -> str:
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if node is None:
        return ""
    try:
        payload = json.loads(node.text())
    except (ValueError, TypeError):
        return ""
    props = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("head", {})
    )
    job = props.get("job") or payload.get("props", {}).get("pageProps", {}).get("job") or {}
    detail = job.get("detail") if isinstance(job, dict) else None
    if isinstance(detail, dict):
        return _join_sections(detail)
    return ""


class WantedClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True
        )
        self._delay = float(SITE_CONFIG["hydrate_delay_s"])

    def __enter__(self) -> "WantedClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, criteria: SearchCriteria) -> list[JobListing]:
        terms = criteria.keywords.split() or [""]
        merged: dict[str, JobListing] = {}
        for term in terms:
            term_criteria = replace(criteria, keywords=term)
            resp = self._client.get(
                SITE_CONFIG["search_url"], params=build_search_params(term_criteria)
            )
            resp.raise_for_status()
            for listing in parse_search_response(resp.json(), criteria):
                merged.setdefault(listing.jobId, listing)
        return list(merged.values())

    def fetch_description(self, listing: JobListing) -> str:
        raw_id = _strip_prefix(listing.jobId)
        api_url = SITE_CONFIG["detail_api_url"].format(job_id=raw_id)
        try:
            resp = self._client.get(api_url)
            resp.raise_for_status()
            body = parse_detail_json(resp.json())
            if body:
                return body
        except (httpx.HTTPError, ValueError):
            pass
        resp = self._client.get(listing.url)
        resp.raise_for_status()
        return parse_detail_html(resp.text)

    def hydrate(self, listings: Iterable[JobListing]) -> list[JobListing]:
        hydrated: list[JobListing] = []
        listings = list(listings)
        for idx, listing in enumerate(listings):
            if idx > 0 and self._delay > 0:
                time.sleep(self._delay)
            listing.description = self.fetch_description(listing)
            hydrated.append(listing)
        return hydrated

    def fetch_by_url(self, url: str, search_name: str) -> JobListing:
        raw_id = parse_listing_url(url)
        api_url = SITE_CONFIG["detail_api_url"].format(job_id=raw_id)
        try:
            resp = self._client.get(api_url)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError):
            payload = None
        if isinstance(payload, dict):
            listing = parse_detail_listing_json(payload, raw_id, search_name)
            if listing.title or listing.description:
                return listing
        # Fall back to scraping the HTML page's __NEXT_DATA__ script.
        page_url = SITE_CONFIG["detail_page_url"].format(job_id=raw_id)
        resp = self._client.get(page_url)
        resp.raise_for_status()
        body = parse_detail_html(resp.text)
        return JobListing(
            jobId=f"{SITE_CONFIG['id_prefix']}{raw_id}",
            search=search_name,
            url=page_url,
            title="",
            company="",
            location="",
            description=body,
            language="ko",
        )
