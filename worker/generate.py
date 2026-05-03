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

# Hard contract for the model. Two valid outputs:
#  1. A plain-text cover letter (after the <chosen-cv> line).
#  2. A skip token: <skip>one short reason</skip> — used when the
#     candidate clearly doesn't meet hard requirements.
# No markdown, no meta-commentary, no apologies, no advice.
COVER_LETTER_DIRECTIVE = """
You are drafting a cover letter that will be submitted to an employer.
The letter must read as if the candidate wrote it themselves.

# Output format

Output MUST be plain text only. No markdown of any kind:
- No headings (no `#`, no `##`).
- No bold, italic, or underline (no `**`, no `*`, no `_`).
- No bullet lists or numbered lists (no `-`, no `*`, no `1.`).
- No backticks, no code blocks, no tables, no blockquotes.
- No links written as `[text](url)` — write them inline as plain URLs if
  needed, but prefer to omit them entirely.

The body is paragraphs of prose separated by blank lines. That is all.

# Voice rules

- Do not refer to yourself as "an AI", "a language model", or any variant.
- Do not include meta-commentary, drafting notes, hedges, disclaimers,
  preambles ("Here is the letter…"), or postscripts ("Let me know if…").
- Do not give the candidate advice or summarise the letter.
- Sign off with the candidate's name only, on the line immediately after
  the closing (e.g. "Regards,") with no blank line between them.

The candidate may legitimately mention Claude, Anthropic, or any other
product/company by name if it's relevant to the role. The voice rule is
about not breaking first-person — it is not a ban on those words.

# Skipping a job

If — and ONLY if — the candidate clearly does not meet a HARD requirement
of the role (e.g. a legally required licence, a degree the role explicitly
demands, a regulated profession the candidate has no background in), do
not write a letter. Instead respond with exactly:

<skip>one short sentence explaining the mismatch</skip>

…and nothing else. No `<chosen-cv>` line, no letter, no commentary.

Use skip sparingly. Do NOT skip for minor gaps, "nice to have" items,
junior/senior level mismatches, or transferable-skill gaps. When in
doubt, write the letter.

# What you produce when you don't skip

Exactly two parts:
1. `<chosen-cv>FILENAME</chosen-cv>` on its own line.
2. The cover letter body as plain text (per the rules above).

Nothing else.
""".strip()


@dataclass
class GenerationResult:
    chosen_cv: str
    body_md: str
    model_used: str  # internal metadata only — never written into body_md


class GenerationError(Exception):
    pass


def _load_system_prompt(language: str) -> str:
    guide_path = GUIDE_DIR / f"{language}.md"
    guide = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""
    parts = [COVER_LETTER_DIRECTIVE]
    if guide:
        parts.append("# Writing guide\n\n" + guide)
    return "\n\n---\n\n".join(parts)


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
        f"Either:\n"
        f"  (a) Pick the single best CV for this role and draft a cover letter "
        f"per the system prompt — output `<chosen-cv>FILENAME</chosen-cv>` on "
        f"its own line, then the letter as plain text (no markdown).\n"
        f"  (b) If the candidate clearly fails a HARD requirement, output only "
        f"`<skip>one short reason</skip>` and nothing else.\n"
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model_id,
        max_tokens=2000,
        system=_load_system_prompt(language),
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")

    skip_match = _detect_skip(raw)
    if skip_match:
        raise GenerationError(f"model skipped: {skip_match}")

    chosen, body = _split_response(raw, fallback_cv=cvs[0].name)
    body = _trim_letter(body)
    body = _strip_markdown(body)
    if _looks_like_refusal(body):
        raise GenerationError("model refused / produced non-letter output")
    return GenerationResult(chosen_cv=chosen, body_md=body, model_used=model_id)


def _detect_skip(raw: str) -> str | None:
    import re

    m = re.search(r"<skip>(.*?)</skip>", raw, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip() or "no reason given"
    return None


def _looks_like_refusal(body: str) -> bool:
    """Catch refusal-style outputs the model emits instead of using <skip>."""
    if not body or len(body) < 20:
        return True
    head = body.lstrip().lower()[:200]
    triggers = (
        "i cannot ",
        "i can't ",
        "i won't ",
        "i will not ",
        "i'm unable to ",
        "i am unable to ",
        "this listing should be",
        "submitting a cover letter would",
    )
    return any(head.startswith(t) or t in head for t in triggers)


_MARKDOWN_PATTERNS = [
    # Fenced code blocks: drop fences but keep inner text.
    (r"```[a-zA-Z0-9_-]*\n?", ""),
    (r"```", ""),
    # ATX headings at start of line: drop leading #'s.
    (r"(?m)^\s{0,3}#{1,6}\s+", ""),
    # Blockquote markers.
    (r"(?m)^\s{0,3}>\s?", ""),
    # Bullet / numbered list markers at line start.
    (r"(?m)^\s*[-*+]\s+", ""),
    (r"(?m)^\s*\d+\.\s+", ""),
    # Bold / italic wrappers — keep inner text.
    (r"\*\*(.+?)\*\*", r"\1"),
    (r"__(.+?)__", r"\1"),
    (r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1"),
    (r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1"),
    # Inline code.
    (r"`([^`]+)`", r"\1"),
    # Markdown links [text](url) -> "text (url)".
    (r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)"),
    # Image syntax.
    (r"!\[[^\]]*\]\([^)]+\)", ""),
    # Horizontal rules.
    (r"(?m)^\s*([-*_])\s*\1\s*\1[\s\1]*$", ""),
]


def _strip_markdown(body: str) -> str:
    import re

    out = body
    for pat, repl in _MARKDOWN_PATTERNS:
        out = re.sub(pat, repl, out)
    # Collapse runs of 3+ blank lines to 2.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _split_response(raw: str, fallback_cv: str) -> tuple[str, str]:
    import re

    match = re.search(r"<chosen-cv>(.*?)</chosen-cv>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback_cv, raw.strip()
    chosen = match.group(1).strip()
    body = raw[match.end():].lstrip("\n")
    return chosen, body


def _trim_letter(body: str) -> str:
    """Strip preamble (H1, jobId comment, title/company header) and trailing
    jobId comment so the stored body starts at the salutation."""
    import re

    cleaned = re.sub(r"<!--\s*jobId:.*?-->", "", body, flags=re.IGNORECASE)
    lines = cleaned.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*(Dear\b|To whom\b|Hello\b|Hi\b)", line, flags=re.IGNORECASE):
            return "\n".join(lines[i:]).strip()
    return cleaned.strip()
