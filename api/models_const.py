"""Anthropic model catalogue + token billing tables.

Token economy:
- Tokens are stored as integer "centitokens" (×100) so we never deal in
  floats. 1 token = 100 centitokens; 0.25 token = 25 centitokens.
- Per-model cost is what we charge the user when billing_mode="tokens".
  The ratios roughly mirror Anthropic's API pricing: Haiku is ~3× cheaper
  than Sonnet, Opus is ~5× more expensive.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    blurb: str
    cost_centitokens: int  # what we charge per cover-letter generation


# Ordered cheapest-to-most-capable. Default is the middle option (Sonnet 4.6).
MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        id="claude-haiku-4-5-20251001",
        label="Haiku 4.5",
        blurb="Cheapest. Fast. Good enough for boilerplate cover letters. (0.25 tokens/letter)",
        cost_centitokens=25,
    ),
    ModelOption(
        id="claude-sonnet-4-6",
        label="Sonnet 4.6 (default)",
        blurb="Best quality-per-dollar. Recommended for most users. (1 token/letter)",
        cost_centitokens=100,
    ),
    ModelOption(
        id="claude-opus-4-7",
        label="Opus 4.7",
        blurb="Highest quality, most expensive. Use for senior roles you really want. (5 tokens/letter)",
        cost_centitokens=500,
    ),
)

DEFAULT_MODEL = "claude-sonnet-4-6"
ALLOWED_MODEL_IDS = {opt.id for opt in MODEL_OPTIONS}
COST_BY_MODEL: dict[str, int] = {opt.id: opt.cost_centitokens for opt in MODEL_OPTIONS}

CENTITOKENS_PER_TOKEN = 100


def tokens_to_centitokens(tokens: float) -> int:
    return int(round(tokens * CENTITOKENS_PER_TOKEN))


def centitokens_to_tokens(ct: int) -> float:
    return ct / CENTITOKENS_PER_TOKEN


@dataclass(frozen=True)
class TokenPackage:
    key: str
    label: str
    centitokens: int
    amount_cents: int  # USD price in cents
    blurb: str


# Stripe Checkout offers these three packages. Higher tiers include a
# bonus, encouraging top-ups while keeping the entry price low.
TOKEN_PACKAGES: tuple[TokenPackage, ...] = (
    TokenPackage(
        key="starter",
        label="Starter",
        centitokens=1000,        # 10 tokens
        amount_cents=500,        # $5.00
        blurb="10 tokens — try it out.",
    ),
    TokenPackage(
        key="standard",
        label="Standard",
        centitokens=5000,        # 50 tokens
        amount_cents=2000,       # $20.00
        blurb="50 tokens — best for regular use.",
    ),
    TokenPackage(
        key="bulk",
        label="Bulk",
        centitokens=15000,       # 150 tokens (50% bonus vs Standard rate)
        amount_cents=5000,       # $50.00
        blurb="150 tokens — 50% bonus over Standard.",
    ),
)

PACKAGES_BY_KEY: dict[str, TokenPackage] = {p.key: p for p in TOKEN_PACKAGES}
