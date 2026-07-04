"""Card Strategy agent — the "which card?" hero and minimum-spend tracker.

PRIVILEGE: standard. Reads the ledger and the card-benefits reference; never
touches raw documents and never moves money.

The agent is a thin conversational layer over deterministic tools: the actual
decision (SPEC.md §2) is computed in app/tools/card_strategy.py, and the live
progress in app/tools/aggregate.py. The model's job is to route the question to
the right tool and speak the result — so the recommendation is always correct and
auditable, and the demo lands the same way every time.
"""

from __future__ import annotations

import datetime

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.tools.aggregate import (
    compute_budget_status,
    compute_card_progress,
    load_budgets,
)
from app.tools.card_strategy import recommend_card
from app.tools.cards import load_cards
from app.tools.categorize import categorize
from app.tools.ledger import load_ledger

_MODEL = "gemini-flash-latest"


def which_card(purchase_description: str, amount_dollars: float) -> dict:
    """Recommend the single best card for a prospective purchase.

    Categorizes the purchase, reads live minimum-spend progress and budget headroom
    from the ledger, and applies the card-strategy decision logic (bonus urgency >
    sooner deadline > category multiplier, with a budget warning if it would breach
    a limit).

    Args:
        purchase_description: What the purchase is (e.g. "a flight", "dinner").
        amount_dollars: The purchase amount in dollars.

    Returns:
        A dict with the recommended card_id, card_name, deciding_factor, a
        one-sentence rationale, and any budget_warning.
    """
    _, bonus_category = categorize(purchase_description)
    ledger = load_ledger()
    cards = compute_card_progress(load_cards(), ledger)
    budgets = compute_budget_status(load_budgets(), ledger)
    rec = recommend_card(
        round(amount_dollars * 100), bonus_category, cards, budgets=budgets
    )
    return {"bonus_category": bonus_category.value, **rec.as_dict()}


def card_progress_summary() -> dict:
    """Report each card's sign-up-bonus progress and days remaining.

    Returns:
        A dict {"cards": [...]} where each entry has the card name, dollars spent
        toward the bonus, the target, dollars remaining, and days left. Cards with
        no active bonus are omitted.
    """
    ledger = load_ledger()
    cards = compute_card_progress(load_cards(), ledger)
    today = datetime.date.today()
    out = []
    for card in cards:
        if card.min_spend_target_cents is None:
            continue
        days_left = (card.bonus_deadline - today).days if card.bonus_deadline else None
        out.append(
            {
                "card": card.name,
                "spent_dollars": card.min_spend_progress_cents / 100,
                "target_dollars": card.min_spend_target_cents / 100,
                "remaining_dollars": card.min_spend_remaining_cents() / 100,
                "days_left": days_left,
            }
        )
    return {"cards": out}


_CARD_STRATEGY_INSTRUCTION = """
You are the Card Strategy agent for Pocket CFO. You answer two kinds of question:

1. "Which card should I use for <purchase>?" -> call `which_card` with a short
   description and the dollar amount, then state the recommended card and its ONE
   deciding reason verbatim from the rationale. If there is a budget_warning,
   include it — never hide an over-budget condition.
2. "Am I on track for the <card> bonus?" / "How's my minimum spend?" -> call
   `card_progress_summary` and report dollars spent, remaining, and days left.

Rules: recommend exactly one card, always with a reason. You never move money and
never tell the user a number you did not get from a tool.
""".strip()


card_strategy_agent = Agent(
    name="card_strategy_agent",
    model=Gemini(model=_MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    description=(
        "Tracks per-card minimum-spend progress and answers 'which card should I "
        "use for this purchase?' with a one-sentence rationale. Read-only."
    ),
    instruction=_CARD_STRATEGY_INSTRUCTION,
    tools=[which_card, card_progress_summary],
)
