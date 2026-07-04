"""Unit tests for categorization (app/tools/categorize.py).

Covers the SPEC.md §3 categorization scenarios: assign a budget + bonus category
in one pass, and LEARN from a user correction so similar future charges follow it.
"""

from __future__ import annotations

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
