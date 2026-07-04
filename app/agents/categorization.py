"""Categorization agent — assigns a budget category and a bonus category in one pass.

PRIVILEGE: standard. Reads/writes categorization data; never touches raw documents.

"One categorization engine, two consumers" (ARCHITECTURE.md §1): the single result
here feeds both the budget tracker (budget category) and the card strategist (bonus
category), so the two features can never disagree about what a purchase is.

The deterministic keyword map in app/tools/categorize.py handles the common cases
and the seed data reliably; the agent adds judgment for genuinely ambiguous
merchants and records user corrections so the system learns over time.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.models import BonusCategory
from app.tools.categorize import categorize, learn_correction

_MODEL = "gemini-flash-latest"

# The closed vocabulary the model must map every merchant into.
_BONUS_VALUES = ", ".join(c.value for c in BonusCategory)


def categorize_transaction(merchant: str) -> dict:
    """Suggest a budget category and a bonus category for a merchant or purchase.

    Args:
        merchant: The merchant name or a short purchase description.

    Returns:
        A dict {budget_category, bonus_category}. bonus_category is one of
        TRAVEL, DINING, GROCERIES, DEFAULT. If it comes back "Uncategorized", use
        your own judgment to choose a sensible budget category and the closest
        bonus category.
    """
    budget_category, bonus_category = categorize(merchant)
    return {"budget_category": budget_category, "bonus_category": bonus_category.value}


def record_correction(merchant: str, budget_category: str, bonus_category: str) -> dict:
    """Remember a user's re-categorization so similar future charges follow it.

    Args:
        merchant: The merchant the user corrected (e.g. "AMAZON").
        budget_category: The budget category to use going forward (e.g. "Groceries").
        bonus_category: One of TRAVEL, DINING, GROCERIES, DEFAULT.

    Returns:
        A confirmation dict.
    """
    learn_correction(merchant, budget_category, BonusCategory(bonus_category))
    return {
        "status": "learned",
        "merchant": merchant,
        "budget_category": budget_category,
        "bonus_category": bonus_category,
    }


_CATEGORIZATION_INSTRUCTION = f"""
You are the Categorization agent for Pocket CFO. For any merchant or purchase you
assign BOTH a budget category (e.g. "Dining", "Groceries", "Travel") and a bonus
category (one of: {_BONUS_VALUES}) in a single pass.

- Call `categorize_transaction` first. If it returns "Uncategorized" or a category
  that is clearly wrong for this merchant, use your judgment: pick a sensible budget
  category and the closest bonus category from the allowed list.
- When the user corrects a categorization ("that Amazon charge was groceries"), call
  `record_correction` so similar future charges follow the correction.

Keep replies short: name the budget category and the bonus category.
""".strip()


categorization_agent = Agent(
    name="categorization_agent",
    model=Gemini(model=_MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    description=(
        "Assigns each transaction a budget category and a card-bonus category in "
        "one pass, and learns from user corrections. Read/write ledger only."
    ),
    instruction=_CATEGORIZATION_INSTRUCTION,
    tools=[categorize_transaction, record_correction],
)
