"""The hero: "which card should I use for this purchase?" (SPEC.md §2).

WHY THIS IS DETERMINISTIC CODE, NOT A PROMPT: the recommendation is a small
multi-variable optimization over live state (bonus progress, deadlines,
multipliers, budgets). A human can't run it at the register, and a model asked to
"just decide" would be inconsistent run-to-run. Implementing the decision logic as
tested code makes every recommendation correct and auditable; the Card Strategy
agent's job is only to phrase the result and hold the conversation. Every figure in
the rationale traces back to cards.yaml or the ledger.

DECISION LOGIC (priority order, highest first) — from SPEC.md §2:
  1. Active-bonus urgency: an unmet minimum-spend bonus with a live deadline
     dwarfs ordinary multiplier differences (a bonus is worth hundreds of dollars).
  2. Deadline proximity: among cards that BOTH have open bonuses, prefer the one
     whose deadline is sooner (more at risk of being missed).
  3. Category multiplier: absent bonus pressure, prefer the highest multiplier for
     this purchase's category.
  4. Budget guardrail (override): if the recommended card would push its category
     budget over the monthly limit, still recommend it but SURFACE the warning —
     never silently hide an over-budget condition (read-only: advise, don't decide).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum

from app.models import BonusCategory, Budget, Card

# Score weights. BONUS_WEIGHT dominates everything so an open, live bonus always
# outranks a mere multiplier edge; URGENCY_BASE - days makes a sooner deadline
# score higher, and it dwarfs the small multiplier term so deadline breaks ties
# among bonus cards. The multiplier term only decides when no bonus is in play.
_BONUS_WEIGHT = 1_000_000.0
_URGENCY_BASE = 1_000.0


class DecidingFactor(StrEnum):
    """The single reason cited in the rationale (SPEC.md §2 requires naming it)."""

    BONUS_GAP = "BONUS_GAP"
    DEADLINE = "DEADLINE"
    MULTIPLIER = "MULTIPLIER"


@dataclass
class CardRecommendation:
    """The result of a which-card query, ready for the agent to speak verbatim."""

    card_id: str
    card_name: str
    deciding_factor: DecidingFactor
    rationale: str
    budget_warning: str | None = None

    def as_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_name": self.card_name,
            "deciding_factor": self.deciding_factor.value,
            "rationale": self.rationale,
            "budget_warning": self.budget_warning,
        }


def _dollars(cents: int) -> str:
    """Format integer cents as a clean dollar string ($3,000 or $12.50)."""
    if cents % 100 == 0:
        return f"${cents // 100:,}"
    return f"${cents / 100:,.2f}"


def _bonus_is_live(card: Card, today: datetime.date) -> bool:
    """True if the card has an unmet bonus whose deadline has not passed."""
    return (
        card.has_open_bonus()
        and card.bonus_deadline is not None
        and (card.bonus_deadline - today).days >= 0
    )


def _score(card: Card, bonus_category: BonusCategory, today: datetime.date) -> float:
    """Score a single card for this purchase (higher = better)."""
    multiplier = card.multiplier_for(bonus_category)
    if _bonus_is_live(card, today):
        assert card.bonus_deadline is not None  # guaranteed by _bonus_is_live
        days_left = (card.bonus_deadline - today).days
        # A live bonus dominates; sooner deadline (fewer days) scores higher.
        return _BONUS_WEIGHT + (_URGENCY_BASE - days_left) + multiplier
    # No bonus pressure: the multiplier alone decides.
    return multiplier


def _budget_for(
    budgets: list[Budget] | None, bonus_category: BonusCategory
) -> Budget | None:
    """Find the budget whose category matches this bonus category (e.g. DINING)."""
    if not budgets or bonus_category == BonusCategory.DEFAULT:
        return None
    return next(
        (b for b in budgets if b.category.upper() == bonus_category.value), None
    )


def _rationale(
    card: Card,
    factor: DecidingFactor,
    amount_cents: int,
    bonus_category: BonusCategory,
    today: datetime.date,
) -> str:
    """Build the one-sentence rationale that names the deciding factor."""
    multiplier = card.multiplier_for(bonus_category)
    cat_label = bonus_category.value.lower()

    if factor is DecidingFactor.BONUS_GAP:
        assert (
            card.bonus_deadline is not None and card.min_spend_target_cents is not None
        )
        days_left = (card.bonus_deadline - today).days
        remaining = card.min_spend_remaining_cents()
        target = _dollars(card.min_spend_target_cents)
        if amount_cents >= remaining:
            core = f"it clears your {target} minimum with {days_left} days to spare"
        else:
            new_progress = _dollars(card.min_spend_progress_cents + amount_cents)
            core = (
                f"it moves you to {new_progress} of {target} with {days_left} days left"
            )
        tail = (
            f", and {cat_label} earns {multiplier:g}x anyway"
            if bonus_category is not BonusCategory.DEFAULT and multiplier > 1
            else ""
        )
        return f"Put it on the {card.name} — {core}{tail}."

    if factor is DecidingFactor.DEADLINE:
        assert card.bonus_deadline is not None
        days_left = (card.bonus_deadline - today).days
        return (
            f"Use the {card.name} — both cards have open bonuses, but its deadline "
            f"is sooner ({days_left} days away), so it's the one more at risk."
        )

    # MULTIPLIER
    where = "everything" if bonus_category is BonusCategory.DEFAULT else cat_label
    return (
        f"Use the {card.name} — it earns {multiplier:g}x on {where}, "
        f"the best rate among your cards."
    )


def recommend_card(
    amount_cents: int,
    bonus_category: BonusCategory,
    cards: list[Card],
    budgets: list[Budget] | None = None,
    today: datetime.date | None = None,
) -> CardRecommendation:
    """Recommend the single best card for a prospective purchase.

    Args:
        amount_cents: the purchase size in cents.
        bonus_category: the purchase's category bucket (from categorization).
        cards: all of the user's cards, with min_spend_progress already computed
            from the ledger.
        budgets: optional budgets, used only to attach an over-limit warning.
        today: reference date for deadline math (defaults to the real today; tests
            pass it explicitly for determinism).

    Returns:
        A CardRecommendation naming the single deciding factor.
    """
    if not cards:
        raise ValueError("recommend_card requires at least one card")
    today = today or datetime.date.today()

    # 1-3. Score every card and take the winner.
    best = max(cards, key=lambda c: _score(c, bonus_category, today))

    # Determine which factor to CITE. If two or more cards have live bonuses, the
    # winner beat the others on deadline; if the winner is the lone bonus card, it
    # won on the bonus gap; otherwise it won purely on multiplier.
    live_bonus_cards = [c for c in cards if _bonus_is_live(c, today)]
    if best in live_bonus_cards:
        factor = (
            DecidingFactor.DEADLINE
            if len(live_bonus_cards) >= 2
            else DecidingFactor.BONUS_GAP
        )
    else:
        factor = DecidingFactor.MULTIPLIER

    rationale = _rationale(best, factor, amount_cents, bonus_category, today)

    # 4. Budget guardrail: never change the pick, but surface an over-limit warning.
    warning: str | None = None
    budget = _budget_for(budgets, bonus_category)
    if budget is not None and budget.is_over_limit(amount_cents):
        over = _dollars(budget.spent_cents + amount_cents - budget.monthly_limit_cents)
        warning = (
            f"Heads up: this would put your {budget.category} budget "
            f"{over} over its {_dollars(budget.monthly_limit_cents)} monthly limit."
        )
        rationale = f"{rationale} {warning}"

    return CardRecommendation(
        card_id=best.id,
        card_name=best.name,
        deciding_factor=factor,
        rationale=rationale,
        budget_warning=warning,
    )
