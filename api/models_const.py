"""Anthropic model catalogue surfaced in the UI dropdown."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    blurb: str


# Ordered cheapest-to-most-capable. Default is the middle option (Sonnet 4.6).
MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        id="claude-haiku-4-5-20251001",
        label="Haiku 4.5",
        blurb="Cheapest. Fast. Good enough for boilerplate cover letters.",
    ),
    ModelOption(
        id="claude-sonnet-4-6",
        label="Sonnet 4.6 (default)",
        blurb="Best quality-per-dollar. Recommended for most users.",
    ),
    ModelOption(
        id="claude-opus-4-7",
        label="Opus 4.7",
        blurb="Highest quality, most expensive. Use for senior roles you really want.",
    ),
)

DEFAULT_MODEL = "claude-sonnet-4-6"
ALLOWED_MODEL_IDS = {opt.id for opt in MODEL_OPTIONS}
