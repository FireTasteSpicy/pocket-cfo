"""Unit tests for categorization (app/tools/categorize.py).

Covers the SPEC.md §3 categorization scenarios: assign a budget + bonus category
in one pass, and LEARN from a user correction so similar future charges follow it.
"""

from __future__ import annotations

import json

from app.models import BonusCategory
from app.tools.categorize import categorize, learn_correction


# ── SPEC: one pass yields both a budget and a bonus category ────────────────
def test_categorizes_merchant_into_budget_and_bonus() -> None:
    budget_cat, bonus_cat = categorize("SQ *BLUE BOTTLE")
    assert budget_cat == "Dining"
    assert bonus_cat is BonusCategory.DINING


def test_categorizes_prospective_purchase_phrases() -> None:
    """The hero query categorizes a phrase like 'a $500 flight' -> TRAVEL."""
    assert categorize("a $500 flight")[1] is BonusCategory.TRAVEL
    assert categorize("$40 dinner with friends")[1] is BonusCategory.DINING
    assert categorize("weekly groceries")[1] is BonusCategory.GROCERIES


def test_seed_merchants_categorize_sensibly() -> None:
    cases = {
        "UNITED AIRLINES 023": BonusCategory.TRAVEL,
        "TRADER JOE'S #123": BonusCategory.GROCERIES,
        "CHIPOTLE 1123": BonusCategory.DINING,
        "SHELL OIL 5567": BonusCategory.DEFAULT,
    }
    for merchant, expected in cases.items():
        assert categorize(merchant)[1] is expected, merchant


def test_unknown_merchant_falls_back() -> None:
    budget_cat, bonus_cat = categorize("ZZZ OBSCURE VENDOR 99")
    assert budget_cat == "Uncategorized"
    assert bonus_cat is BonusCategory.DEFAULT


# ── SPEC: learn from a user correction ──────────────────────────────────────
def test_learns_from_correction(tmp_path) -> None:
    path = tmp_path / "corrections.json"
    # Baseline: an Amazon charge defaults to Shopping.
    assert categorize("AMAZON MARKETPLACE", corrections_path=path)[0] == "Shopping"
    # The user re-categorizes Amazon as Groceries...
    learn_correction("AMAZON", "Groceries", BonusCategory.GROCERIES, path=path)
    # ...so a similar future Amazon charge now prefers Groceries.
    budget_cat, bonus_cat = categorize("AMAZON.COM ORDER", corrections_path=path)
    assert budget_cat == "Groceries"
    assert bonus_cat is BonusCategory.GROCERIES


def test_correction_does_not_collide_with_unrelated_merchants(tmp_path) -> None:
    """A correction keyed 'bar' (from 'Bar Luca') must not hijack merchants that
    merely CONTAIN 'bar' as a substring without it being a whole word/token --
    e.g. 'BARNES & NOBLE' or 'CROWBAR' -- since a naive `key in text` substring
    check would match all three and silently poison unrelated categorization."""
    path = tmp_path / "corrections.json"
    learn_correction("Bar Luca", "Dining", BonusCategory.DINING, path=path)
    # The actual corrected merchant matches (word-boundary match on "bar").
    assert categorize("Bar Luca receipt", corrections_path=path)[0] == "Dining"
    # These must NOT be hijacked -- "bar" is not a whole token in either. (Bare
    # "CROWBAR", not "CROWBAR BREWING", to isolate the correction check from the
    # UNRELATED built-in "bar " Dining keyword, which would substring-match
    # "crowbar brewing" across the word boundary regardless of this fix.)
    assert categorize("BARNES & NOBLE", corrections_path=path)[0] != "Dining"
    assert categorize("CROWBAR", corrections_path=path)[0] != "Dining"


def test_correction_key_skips_stopwords_and_processor_prefixes(tmp_path) -> None:
    """Found live: correcting 'SQ *THE LOCAL PANTRY' keyed to the stopword 'the'
    (the first token with >=3 alpha chars), which would then hijack every future
    merchant containing that common word. The key must skip to 'local' instead."""
    path = tmp_path / "corrections.json"
    learn_correction(
        "SQ *THE LOCAL PANTRY", "Groceries", BonusCategory.GROCERIES, path=path
    )
    stored_key = next(iter(json.loads(path.read_text())))
    assert stored_key not in {"sq", "the"}
    assert stored_key == "local"
    # The real merchant still matches...
    assert categorize("SQ *THE LOCAL PANTRY", corrections_path=path)[0] == "Groceries"
    # ...but an unrelated merchant that merely contains "the" must NOT be hijacked.
    assert categorize("THE HOME DEPOT", corrections_path=path)[0] != "Groceries"
