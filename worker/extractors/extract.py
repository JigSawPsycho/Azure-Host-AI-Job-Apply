"""Best-effort CV-to-plaintext.

Markdown: as-is. PDF: pdfplumber. DOCX: python-docx. Anything else
raises ExtractError so the worker can show "we couldn't read this CV"
rather than feed garbage to the LLM.
"""
from __future__ import annotations

import io
from dataclasses import dataclass


@dataclass
class CVFile:
    name: str
    content: bytes  # raw bytes pulled from GitHub
    sha: str


class ExtractError(Exception):
    pass


def extract_text(cv: CVFile) -> str:
    name = cv.name.lower()
    if name.endswith(".md") or name.endswith(".markdown") or name.endswith(".txt"):
        return cv.content.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        return _extract_pdf(cv.content)
    if name.endswith(".docx"):
        return _extract_docx(cv.content)
    raise ExtractError(f"unsupported CV format: {cv.name}")


def _extract_pdf(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ExtractError("pdfplumber is not installed") from exc
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    text = "\n\n".join(pages).strip()
    if not text:
        raise ExtractError("PDF contained no extractable text (scanned image?)")
    return text


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ExtractError("python-docx is not installed") from exc
    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ExtractError("DOCX contained no extractable text")
    return text
