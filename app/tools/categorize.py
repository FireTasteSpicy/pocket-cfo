"""Categorization — assign a budget category AND a bonus category in one pass.

DESIGN (SPEC.md §3 "Categorization"): one classification feeds two consumers — the
budget tracker (budget category, e.g. "Dining") and the card strategist (bonus
category, e.g. DINING). Computing them together is what keeps the two features from
ever disagreeing about "what is this purchase?".

This module is the deterministic backbone: a keyword map that reliably categorizes
common merchants AND prospective-purchase phrases ("a $500 flight" -> TRAVEL). The
Categorization *agent* layers a model on top for genuinely ambiguous merchants, but
the seed data and the hero purchase phrases resolve here without any model call —
which keeps the demo and the eval reproducible.

It also implements "learn from a user correction": a correction is remembered and
preferred for similar future merchants.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.models import BonusCategory

# User corrections are personal data -> gitignored, like the ledger.
CORRECTIONS_PATH = Path("app/data/corrections.json")

# Ordered keyword rules: the first rule with a matching keyword wins. Each maps to
# (budget_category, bonus_category). Keywords are matched case-insensitively as
# substrings, so both merchant descriptors and plain purchase words are covered.
_RULES: list[tuple[list[str], str, BonusCategory]] = [
    (
        [
            "airline",
            "airlines",
            "flight",
            "delta",
            "united",
            "marriott",
            "hotel",
            "airbnb",
            "uber",
            "lyft",
            "amtrak",
            "expedia",
            "travel",
        ],
        "Travel",
        BonusCategory.TRAVEL,
    ),
    (
        [
            "restaurant",
            "dining",
            "dinner",
            "lunch",
            "cafe",
            "coffee",
            "blue bottle",
            "chipotle",
            "sushi",
            "olive garden",
            "starbucks",
            "mcdonald",
            "doordash",
            "grubhub",
            "pizza",
            "bar ",
        ],
        "Dining",
        BonusCategory.DINING,
    ),
    (
        [
            "grocery",
            "groceries",
            "trader joe",
            "whole foods",
            "safeway",
            "costco",
            "kroger",
            "aldi",
            "supermarket",
        ],
        "Groceries",
        BonusCategory.GROCERIES,
    ),
    (
        ["amazon", "target", "walmart", "apple", "best buy", "shopping", "store"],
        "Shopping",
        BonusCategory.DEFAULT,
    ),
    (
        ["shell", "chevron", "exxon", "gas", "fuel", "petrol"],
        "Gas",
        BonusCategory.DEFAULT,
    ),
    (
        ["netflix", "spotify", "hulu", "subscription", "apple.com/bill"],
        "Subscriptions",
        BonusCategory.DEFAULT,
    ),
]

_UNCATEGORIZED = ("Uncategorized", BonusCategory.DEFAULT)

# Skipped when picking a correction key: payment-processor prefixes and common
# stopwords/business suffixes that are not distinguishing parts of a merchant
# name. Found in review: "SQ *THE LOCAL PANTRY" keyed to "the" (the first token
# with >=3 alpha chars), which -- combined with word-boundary matching in
# categorize() -- would then hijack every future merchant containing "the".
_KEY_STOPWORDS = {
    "sq",
    "tst",
    "pos",
    "the",
    "and",
    "for",
    "of",
    "inc",
    "llc",
    "ltd",
    "corp",
    "co",
}


def _correction_key(merchant: str) -> str:
    """A stable key for a correction: the first DISTINGUISHING alphabetic token.

    "AMAZON MARKETPLACE" and "AMAZON.COM" both key to "amazon", so a correction on
    one applies to the other. Stopwords (see _KEY_STOPWORDS) are skipped so the
    key is never a generic word that would match unrelated merchants.
    """
    for token in merchant.lower().replace("*", " ").split():
        alpha = "".join(ch for ch in token if ch.isalpha())
        if len(alpha) >= 3 and alpha not in _KEY_STOPWORDS:
            return alpha
    return merchant.strip().lower()


def load_corrections(path: Path = CORRECTIONS_PATH) -> dict[str, list[str]]:
    """Load the merchant->[budget_category, bonus_category] corrections map."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def learn_correction(
    merchant: str,
    budget_category: str,
    bonus_category: BonusCategory,
    path: Path = CORRECTIONS_PATH,
) -> None:
    """Remember that `merchant` should be categorized this way from now on."""
    corrections = load_corrections(path)
    corrections[_correction_key(merchant)] = [budget_category, bonus_category.value]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corrections, indent=2), encoding="utf-8")


def categorize(
    text: str, corrections_path: Path = CORRECTIONS_PATH
) -> tuple[str, BonusCategory]:
    """Categorize a merchant name or purchase phrase.

    Returns (budget_category, bonus_category). User corrections take priority over
    the built-in rules (that is what "learning from corrections" means); unknown
    input falls back to ("Uncategorized", DEFAULT).
    """
    lower = text.lower()

    # 1. Corrections win — a remembered merchant is categorized as the user asked.
    # Matched at a WORD BOUNDARY (\b), not raw substring containment: a correction
    # keyed "bar" (from "Bar Luca") must match "AMAZON.COM" via the dot boundary
    # after "amazon", but must NOT silently hijack "BARNES & NOBLE" or "CROWBAR" --
    # a bare `key in lower` check would match all three, letting one correction
    # poison unrelated future merchants (found in review; see test_categorize.py).
    for key, (budget_cat, bonus_cat) in load_corrections(corrections_path).items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return budget_cat, BonusCategory(bonus_cat)

    # 2. Built-in keyword rules.
    for keywords, budget_cat, bonus_cat in _RULES:
        if any(keyword in lower for keyword in keywords):
            return budget_cat, bonus_cat

    # 3. Unknown.
    return _UNCATEGORIZED
