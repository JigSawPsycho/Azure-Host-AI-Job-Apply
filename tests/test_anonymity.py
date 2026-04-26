"""The system prompt instructs the model to keep first-person voice and
avoid meta-commentary, but the words "claude" / "anthropic" are NOT
banned — devs applying to Anthropic, or to companies that integrate
Claude, would have those words appear legitimately. The safety net is
human review in the apply UI."""
from __future__ import annotations

from worker.generate import ANONYMITY_CLAUSE, _split_response


def test_anonymity_clause_targets_meta_voice_not_brand_names():
    text = ANONYMITY_CLAUSE.lower()
    # The clause forbids meta self-identification...
    assert "an ai" in text or "a language model" in text
    # ...but explicitly carves out legitimate product/company mentions.
    assert "may legitimately mention" in text


def test_split_response_pulls_chosen_cv_tag():
    raw = "<chosen-cv>backend.md</chosen-cv>\n\nDear hiring manager,\n\nHello.\n"
    chosen, body = _split_response(raw, fallback_cv="other.md")
    assert chosen == "backend.md"
    assert body.startswith("Dear hiring manager")


def test_split_response_falls_back_when_tag_missing():
    raw = "Dear hiring manager,\n\nHello.\n"
    chosen, body = _split_response(raw, fallback_cv="default.md")
    assert chosen == "default.md"
    assert "Dear hiring manager" in body
