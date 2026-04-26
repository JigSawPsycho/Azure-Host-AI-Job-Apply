"""Reads/writes the seen.json and rejected.json state files."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class SeenIndex:
    """Dedup index for jobIds the scraper has already written to inbox."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, str]] = {}
        if path.exists():
            self._data = json.loads(path.read_text() or "{}")

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._data

    def record(self, job_id: str, url: str, title: str) -> None:
        self._data[job_id] = {
            "first_seen": date.today().isoformat(),
            "url": url,
            "title": title,
            "status": "inbox",
        }

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")


def load_rejected(path: Path) -> set[str]:
    if not path.exists():
        return set()
    raw = json.loads(path.read_text() or "[]")
    return {str(x) for x in raw}
