"""Unit tests for the hero: the which-card recommender (app/tools/card_strategy.py).

Pins all four SPEC.md §3 "Which-card recommendation" scenarios as deterministic
tests. This is the demo centerpiece, so its logic must be provably correct — not
left to a model's run-to-run whim.
"""

from __future__ import annotations

import datetime

from app.models import BonusCategory, Budget, Card
from app.tools.card_strategy import DecidingFactor, recommend_card
from app.tools.cards import get_card, load_cards

# Fixed "today" so deadline math is deterministic (matches cards.yaml's Amex date).
_TODAY = datetime.date(2026, 7, 4)


# ── cards.yaml loads correctly ──────────────────────────────────────────────
def test_load_cards_from_reference_skill() -> None:
    cards = load_cards()
    amex = get_card(cards, "amex_gold")
    assert amex is not None
    assert amex.min_spend_target_cents == 300_000
    assert amex.multiplier_for(BonusCategory.DINING) == 4.0
    # Chase has the higher everyday travel rate but no active bonus.
    chase = get_card(cards, "chase_sapphire")
    assert chase.multiplier_for(BonusCategory.TRAVEL) == 5.0
    assert chase.has_open_bonus() is False


# ── SPEC scenario 1: bonus urgency beats a higher everyday multiplier ────────
def test_bonus_urgency_wins_over_higher_multiplier() -> None:
    cards = load_cards()
    get_card(cards, "amex_gold").min_spend_progress_cents = 250_000  # $2,500 done
    rec = recommend_card(50_000, BonusCategory.TRAVEL, cards, today=_TODAY)
    assert rec.card_id == "amex_gold"  # NOT chase, despite chase's 5x travel
    assert rec.deciding_factor is DecidingFactor.BONUS_GAP
    assert "$3,000" in rec.rationale
    assert "9 days" in rec.rationale
    assert "clears" in rec.rationale


# ── SPEC scenario 2: sooner deadline breaks a tie between two bonus cards ────
def test_sooner_deadline_breaks_tie() -> None:
    mult = {BonusCategory.TRAVEL: 2.0, BonusCategory.DEFAULT: 1.0}
    card_a = Card(
        id="a",
        name="Card A",
        min_spend_target_cents=200_000,
        min_spend_progress_cents=100_000,
        bonus_deadline=_TODAY + datetime.timedelta(days=5),
        category_multipliers=mult,
    )
    card_b = Card(
        id="b",
        name="Card B",
        min_spend_target_cents=200_000,
        min_spend_progress_cents=100_000,
        bonus_deadline=_TODAY + datetime.timedelta(days=25),
        category_multipliers=mult,
    )
    rec = recommend_card(20_000, BonusCategory.TRAVEL, [card_b, card_a], today=_TODAY)
    assert rec.card_id == "a"  # sooner deadline
    assert rec.deciding_factor is DecidingFactor.DEADLINE
    assert "sooner" in rec.rationale
    assert "5 days" in rec.rationale


# ── SPEC scenario 3: fall back to the category multiplier with no bonus ─────
def test_falls_back_to_multiplier_without_bonus() -> None:
    card_x = Card(
        id="x",
        name="Card X",
        category_multipliers={BonusCategory.DINING: 3.0, BonusCategory.DEFAULT: 1.0},
    )
    card_y = Card(
        id="y",
        name="Card Y",
        category_multipliers={BonusCategory.DINING: 1.0, BonusCategory.DEFAULT: 1.0},
    )
    rec = recommend_card(4_000, BonusCategory.DINING, [card_x, card_y], today=_TODAY)
    assert rec.card_id == "x"
    assert rec.deciding_factor is DecidingFactor.MULTIPLIER
    assert "3x" in rec.rationale
    assert "dining" in rec.rationale


# ── SPEC scenario 4: surface a budget warning without hiding the pick ───────
def test_budget_warning_surfaced_without_changing_pick() -> None:
    card = Card(
        id="x",
        name="Card X",
        category_multipliers={BonusCategory.DINING: 3.0, BonusCategory.DEFAULT: 1.0},
    )
    # Dining budget nearly exhausted: $390 of $400 spent; a $40 dinner breaches it.
    budgets = [
        Budget(category="Dining", monthly_limit_cents=40_000, spent_cents=39_000)
    ]
    rec = recommend_card(
        4_000, BonusCategory.DINING, [card], budgets=budgets, today=_TODAY
    )
    assert rec.card_id == "x"  # still names the best card
    assert rec.budget_warning is not None
    assert "over" in rec.rationale.lower()
    assert "Dining" in rec.rationale


def test_no_budget_warning_when_within_limit() -> None:
    card = Card(id="x", name="Card X", category_multipliers={BonusCategory.DINING: 3.0})
    budgets = [Budget(category="Dining", monthly_limit_cents=40_000, spent_cents=1_000)]
    rec = recommend_card(
        4_000, BonusCategory.DINING, [card], budgets=budgets, today=_TODAY
    )
    assert rec.budget_warning is None
