"""The model identifier (and any provider name) must never appear in
generated cover letter bodies. _enforce_anonymity is the last line of
defence — verify it bites."""
from __future__ import annotations

import pytest

from worker.generate import GenerationError, _enforce_anonymity


def test_clean_letter_passes():
    _enforce_anonymity(
        "Dear hiring manager,\n\nI'm excited to apply for the role.\n\nKind regards,\nMichael"
    )


@pytest.mark.parametrize(
    "term",
    ["Claude", "Anthropic", "as an AI", "I am an AI", "as a language model", "I am a language model"],
)
def test_forbidden_terms_rejected(term: str):
    body = f"Dear hiring manager,\n\n{term} would be delighted to help.\n"
    with pytest.raises(GenerationError):
        _enforce_anonymity(body)


def test_case_insensitive():
    with pytest.raises(GenerationError):
        _enforce_anonymity("CLAUDE crafted this letter for you.")
