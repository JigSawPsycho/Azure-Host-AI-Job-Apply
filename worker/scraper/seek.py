"""Seek AU/NZ search and detail-page fetcher.

Uses the public JSON search endpoint (jobsearch/v5) plus HTML scraping of the
detail page for the full job ad body. AU hits seek.com.au (siteKey AU-Main);
NZ hits nz.seek.com (NZ-Main). If Seek changes the endpoint or starts blocking
the request, SITE_CONFIG and the two parse functions are the swap points.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from .models import JobListing, SearchCriteria

SITE_CONFIG = {
    "au": {
        "search_url": "https://www.seek.com.au/api/jobsearch/v5/search",
        "detail_url": "https://www.seek.com.au/job/{job_id}",
        "site_key": "AU-Main",
        "hosts": ("www.seek.com.au", "seek.com.au"),
    },
    "nz": {
        "search_url": "https://nz.seek.com/api/jobsearch/v5/search",
        "detail_url": "https://nz.seek.com/job/{job_id}",
        "site_key": "NZ-Main",
        "hosts": ("nz.seek.com",),
    },
}

JOB_PATH_RE = re.compile(r"/job/(\d+)")

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

SEARCH_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

WORK_TYPE_CODES = {
    "full-time": "242",
    "part-time": "243",
    "contract": "244",
    "casual": "245",
    "temporary": "244",
}

WORK_ARRANGEMENT_CODES = {
    "remote": "2",
    "hybrid": "3",
    "onsite": "1",
}


def build_search_params(criteria: SearchCriteria, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {
        "siteKey": SITE_CONFIG[criteria.site]["site_key"],
        "sourcesystem": "houston",
        "page": page,
        "pageSize": 22,
        "sortmode": "ListedDate",
    }
    if criteria.keywords:
        params["keywords"] = criteria.keywords
    if criteria.location:
        params["where"] = criteria.location
    if criteria.work_type:
        codes = [WORK_TYPE_CODES[v] for v in criteria.work_type if v in WORK_TYPE_CODES]
        if codes:
            params["worktype"] = ",".join(codes)
    if criteria.work_arrangement:
        codes = [
            WORK_ARRANGEMENT_CODES[v]
            for v in criteria.work_arrangement
            if v in WORK_ARRANGEMENT_CODES
        ]
        if codes:
            params["workarrangement"] = ",".join(codes)
    if criteria.salary_min:
        params["salaryrange"] = f"{criteria.salary_min}-"
        params["salarytype"] = "annual"
    return params


def _first_location(item: dict[str, Any]) -> str:
    if item.get("location"):
        return str(item["location"]).strip()
    for loc in item.get("locations") or []:
        label = loc.get("label") if isinstance(loc, dict) else None
        if label:
            return str(label).strip()
    return ""


def _work_type(item: dict[str, Any]) -> str:
    if item.get("workType"):
        return str(item["workType"]).strip()
    types = item.get("workTypes") or []
    return ", ".join(str(t).strip() for t in types if str(t).strip())


def _work_arrangement(item: dict[str, Any]) -> str:
    if item.get("workArrangement"):
        return str(item["workArrangement"]).strip()
    arr = item.get("workArrangements") or {}
    if isinstance(arr, dict):
        entries = arr.get("data") or []
        labels = [
            (e.get("label") or {}).get("text", "")
            for e in entries
            if isinstance(e, dict)
        ]
        return ", ".join(l.strip() for l in labels if l and l.strip())
    return ""


def _salary(item: dict[str, Any]) -> str:
    return str(item.get("salary") or item.get("salaryLabel") or "").strip()


def parse_search_response(payload: dict[str, Any], criteria: SearchCriteria) -> list[JobListing]:
    listings: list[JobListing] = []
    for item in payload.get("data", []) or []:
        title = str(item.get("title") or "").strip()
        company = str(
            item.get("advertiser", {}).get("description")
            or item.get("companyName")
            or ""
        ).strip()
        description_teaser = str(item.get("teaser") or "").strip()

        haystack = " ".join([title, description_teaser]).lower()
        if any(bad.lower() in haystack for bad in criteria.exclude_keywords):
            continue

        job_id = str(item.get("id") or "").strip()
        if not job_id:
            continue

        listings.append(
            JobListing(
                jobId=job_id,
                search=criteria.name,
                url=SITE_CONFIG[criteria.site]["detail_url"].format(job_id=job_id),
                title=title,
                company=company,
                location=_first_location(item),
                work_arrangement=_work_arrangement(item),
                work_type=_work_type(item),
                salary=_salary(item),
                posted_at=str(item.get("listingDate") or "")[:10],
                teaser=description_teaser,
                bullets=[
                    str(b).strip()
                    for b in (item.get("bulletPoints") or [])
                    if str(b).strip()
                ],
            )
        )
    return listings


def parse_detail_html(html: str) -> str:
    tree = HTMLParser(html)
    node = tree.css_first("[data-automation='jobAdDetails']") or tree.css_first(
        "#jobAdDetails"
    )
    if not node:
        return ""
    return node.text(separator="\n", strip=True)


def parse_listing_url(url: str) -> tuple[str, str]:
    """Return (site, job_id) for a Seek detail URL.

    Raises ValueError when the URL doesn't belong to a supported Seek host
    or doesn't contain a numeric job id.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    site = next(
        (s for s, cfg in SITE_CONFIG.items() if host in cfg["hosts"]),
        None,
    )
    if site is None:
        raise ValueError(f"Unsupported Seek host: {host!r}")
    match = JOB_PATH_RE.search(parsed.path or "")
    if not match:
        raise ValueError(f"Could not extract Seek job id from {url!r}")
    return site, match.group(1)


def _jsonld_jobpostings(html: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for node in tree.css("script[type='application/ld+json']"):
        try:
            payload = json.loads(node.text())
        except (ValueError, TypeError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                out.append(entry)
    return out


def _jsonld_location(meta: dict[str, Any]) -> str:
    job_loc = meta.get("jobLocation")
    if isinstance(job_loc, list):
        job_loc = job_loc[0] if job_loc else None
    if not isinstance(job_loc, dict):
        return ""
    addr = job_loc.get("address")
    if isinstance(addr, dict):
        parts = [
            str(addr.get("addressLocality") or "").strip(),
            str(addr.get("addressRegion") or "").strip(),
        ]
        return " ".join(p for p in parts if p)
    if isinstance(addr, str):
        return addr.strip()
    return ""


def _jsonld_salary(meta: dict[str, Any]) -> str:
    base = meta.get("baseSalary")
    if not isinstance(base, dict):
        return ""
    value = base.get("value")
    if isinstance(value, dict):
        lo = value.get("minValue") or value.get("value")
        hi = value.get("maxValue")
        if lo and hi:
            return f"{lo}-{hi}"
        return str(lo or hi or "").strip()
    if value:
        return str(value).strip()
    return ""


def _jsonld_employment_type(meta: dict[str, Any]) -> str:
    et = meta.get("employmentType")
    if isinstance(et, list):
        return ", ".join(str(x).strip() for x in et if str(x).strip())
    return str(et or "").strip()


def parse_detail_listing(
    html: str, site: str, job_id: str, search_name: str
) -> JobListing:
    postings = _jsonld_jobpostings(html)
    meta = postings[0] if postings else {}

    org = meta.get("hiringOrganization") or {}
    company = ""
    if isinstance(org, dict):
        company = str(org.get("name") or "").strip()

    title = str(meta.get("title") or "").strip()
    if not title:
        tree = HTMLParser(html)
        node = tree.css_first("[data-automation='job-detail-title']")
        if node:
            title = node.text(strip=True)

    posted_at = str(meta.get("datePosted") or "")[:10]

    return JobListing(
        jobId=job_id,
        search=search_name,
        url=SITE_CONFIG[site]["detail_url"].format(job_id=job_id),
        title=title,
        company=company,
        location=_jsonld_location(meta),
        work_arrangement="",
        work_type=_jsonld_employment_type(meta),
        salary=_jsonld_salary(meta),
        posted_at=posted_at,
        teaser="",
        bullets=[],
        description=parse_detail_html(html),
    )


class SeekClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True
        )

    def __enter__(self) -> "SeekClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._owns_client:
            self._client.close()

    def _site_origin(self, site: str) -> str:
        return SITE_CONFIG[site]["detail_url"].split("/job/")[0]

    def _warm_session(self, site: str) -> None:
        if getattr(self._client, "_seek_warmed", set()).__contains__(site):
            return
        try:
            self._client.get(self._site_origin(site) + "/")
        except httpx.HTTPError:
            pass
        warmed = getattr(self._client, "_seek_warmed", set())
        warmed.add(site)
        self._client._seek_warmed = warmed  # type: ignore[attr-defined]

    def search(self, criteria: SearchCriteria) -> list[JobListing]:
        self._warm_session(criteria.site)
        url = SITE_CONFIG[criteria.site]["search_url"]
        origin = self._site_origin(criteria.site)
        headers = {**SEARCH_HEADERS, "Referer": origin + "/"}
        resp = self._client.get(
            url, params=build_search_params(criteria), headers=headers
        )
        resp.raise_for_status()
        return parse_search_response(resp.json(), criteria)

    def fetch_description(self, listing: JobListing) -> str:
        site, _ = parse_listing_url(listing.url)
        self._warm_session(site)
        headers = {"Referer": self._site_origin(site) + "/"}
        resp = self._client.get(listing.url, headers=headers)
        resp.raise_for_status()
        return parse_detail_html(resp.text)

    def hydrate(self, listings: Iterable[JobListing]) -> list[JobListing]:
        hydrated: list[JobListing] = []
        for listing in listings:
            listing.description = self.fetch_description(listing)
            hydrated.append(listing)
        return hydrated

    def fetch_by_url(self, url: str, search_name: str) -> JobListing:
        site, job_id = parse_listing_url(url)
        self._warm_session(site)
        canonical = SITE_CONFIG[site]["detail_url"].format(job_id=job_id)
        headers = {"Referer": self._site_origin(site) + "/"}
        resp = self._client.get(canonical, headers=headers)
        resp.raise_for_status()
        return parse_detail_listing(resp.text, site, job_id, search_name)
