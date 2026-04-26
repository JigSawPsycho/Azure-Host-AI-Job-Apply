"""Anthropic call: produce a cover letter for one job + a set of user CVs.

Hard rule: the model must never identify itself or its provider in the
output. The system prompt enforces this, and we run a defensive
post-check before persisting.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anthropic

from .extractors import CVFile, extract_text

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
GUIDE_DIR = Path(__file__).resolve().parent / "writing_guides"

# Hard constraint shown to every model. Keeps the model identifier
# out of any artefact the employer can see.
ANONYMITY_CLAUSE = """
You are drafting a cover letter that will be submitted to an employer
verbatim. The employer must not be able to tell that AI assisted with
this letter. Therefore, in your output:

- Never name yourself, never mention "Claude", "Anthropic", "AI", "LLM",
  "language model", "model", or any provider/product name.
- Never include meta-commentary about how the letter was generated.
- Never include disclaimers about limitations, capabilities, or training data.
- Never sign off with anything other than the candidate's name.

Your output is the letter itself. Nothing else.
""".strip()

# Forbidden substrings (case-insensitive) we refuse to ship in the body.
_FORBIDDEN = (
    "claude",
    "anthropic",
    "as an ai",
    "as a language model",
    "i am an ai",
    "i am a language model",
)


@dataclass
class GenerationResult:
    chosen_cv: str
    body_md: str
    model_used: str  # internal metadata only — never written into body_md


class GenerationError(Exception):
    pass


def _load_system_prompt(language: str) -> str:
    base = (PROMPT_DIR / "process-job.md").read_text()
    guide = (GUIDE_DIR / f"{language}.md").read_text()
    return f"{base}\n\n---\n\n{guide}\n\n---\n\n{ANONYMITY_CLAUSE}"


def generate_cover_letter(
    api_key: str,
    model_id: str,
    job: dict,
    cvs: list[CVFile],
    language: str = "en",
) -> GenerationResult:
    if not cvs:
        raise GenerationError("no CVs available to base the letter on")

    cv_blocks = []
    for cv in cvs:
        try:
            text = extract_text(cv)
        except Exception as exc:  # surface, don't crash the run
            text = f"<<could not extract text from {cv.name}: {exc}>>"
        cv_blocks.append(f"### CV: {cv.name}\n\n{text}")
    cvs_combined = "\n\n".join(cv_blocks)

    user_msg = (
        f"# Job listing\n\n"
        f"- Title: {job.get('title', '')}\n"
        f"- Company: {job.get('company', '')}\n"
        f"- Location: {job.get('location', '')}\n"
        f"- URL: {job.get('url', '')}\n\n"
        f"## Description\n\n{job.get('description', '') or job.get('teaser', '')}\n\n"
        f"# Candidate CVs\n\n"
        f"{cvs_combined}\n\n"
        f"# Task\n\n"
        f"Pick the single best CV for this role and draft a cover letter "
        f"using the rules in the system prompt. Respond with exactly two sections:\n\n"
        f'`<chosen-cv>FILENAME</chosen-cv>` on its own line, then the letter '
        f"as markdown."
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model_id,
        max_tokens=2000,
        system=_load_system_prompt(language),
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")

    chosen, body = _split_response(raw, fallback_cv=cvs[0].name)
    _enforce_anonymity(body)
    return GenerationResult(chosen_cv=chosen, body_md=body.strip(), model_used=model_id)


def _split_response(raw: str, fallback_cv: str) -> tuple[str, str]:
    import re

    match = re.search(r"<chosen-cv>(.*?)</chosen-cv>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback_cv, raw.strip()
    chosen = match.group(1).strip()
    body = raw[match.end():].lstrip("\n")
    return chosen, body


def _enforce_anonymity(body: str) -> None:
    lower = body.lower()
    for term in _FORBIDDEN:
        if term in lower:
            raise GenerationError(
                f"generated letter contained forbidden term {term!r}; "
                f"refusing to persist"
            )
