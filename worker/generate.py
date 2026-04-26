"""Anthropic call: produce a cover letter for one job + a set of user CVs.

The system prompt instructs the model not to identify itself or its
provider in a meta sense. We do NOT post-filter on the words "claude"
or "anthropic" — those legitimately appear in cover letters for jobs
at Anthropic, or at any company that integrates Claude. The safety net
is the human-in-the-loop review in the apply UI before mark-sent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anthropic

from .extractors import CVFile, extract_text

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
GUIDE_DIR = Path(__file__).resolve().parent / "writing_guides"

# Hard constraint shown to every model. Keeps meta-commentary about
# the model itself out of the letter — the candidate may freely
# reference "Claude" or "Anthropic" as a product or employer if that's
# legitimately what the role is about.
ANONYMITY_CLAUSE = """
You are drafting a cover letter that will be submitted to an employer.
The letter must read as if the candidate wrote it themselves. Therefore:

- Do not refer to yourself as "an AI", "a language model", or any
  variant. The letter is in the candidate's voice, not yours.
- Do not include meta-commentary about how the letter was generated,
  drafting notes, hedges, or disclaimers about your capabilities.
- Sign off with the candidate's name only.

Note: the candidate may legitimately mention Claude, Anthropic, or any
other product/company by name if it's relevant to the role they're
applying for. The rule above is about not breaking the first-person
voice — it is not a ban on those words.

Your output is the letter itself. Nothing else.
""".strip()


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
    return GenerationResult(chosen_cv=chosen, body_md=body.strip(), model_used=model_id)


def _split_response(raw: str, fallback_cv: str) -> tuple[str, str]:
    import re

    match = re.search(r"<chosen-cv>(.*?)</chosen-cv>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback_cv, raw.strip()
    chosen = match.group(1).strip()
    body = raw[match.end():].lstrip("\n")
    return chosen, body
