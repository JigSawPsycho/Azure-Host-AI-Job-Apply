"""Fetch CV files from a user's GitHub repo and (optionally) deliver PRs."""
from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


@dataclass
class FetchedFile:
    name: str
    path: str
    sha: str
    content: bytes


class GitHubClient:
    def __init__(self, token: str, repo_full_name: str) -> None:
        self.token = token
        self.repo = repo_full_name
        self._http = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20,
        )

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc) -> None:
        self._http.close()

    def list_cvs(self, cv_dir: str) -> list[FetchedFile]:
        """List CV files under cv_dir (non-recursive). Pulls each blob."""
        resp = self._http.get(f"/repos/{self.repo}/contents/{cv_dir.strip('/')}")
        resp.raise_for_status()
        entries = resp.json()
        if not isinstance(entries, list):
            raise RuntimeError(f"{cv_dir} is not a directory in {self.repo}")
        files: list[FetchedFile] = []
        for entry in entries:
            if entry.get("type") != "file":
                continue
            name = entry["name"]
            if not _looks_like_cv(name):
                continue
            blob = self._http.get(entry["git_url"])
            blob.raise_for_status()
            content = base64.b64decode(blob.json()["content"])
            files.append(FetchedFile(name=name, path=entry["path"], sha=entry["sha"], content=content))
        return files


_CV_EXTS = {".md", ".markdown", ".txt", ".pdf", ".docx"}


def _looks_like_cv(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _CV_EXTS)
