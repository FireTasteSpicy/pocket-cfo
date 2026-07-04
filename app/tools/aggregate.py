"""Aggregate the ledger into live card progress and budget status.

This is the "one categorization engine, two consumers" join point: the same
ledger feeds both the card strategist (per-card minimum-spend progress) and the
budget tracker (spent-vs-limit per category). Both are deterministic sums over the
ledger, so the numbers the agent reports are exact and reproducible.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import yaml

from app.models import Budget, Card, Transaction

# Default budget config (tracked, not user data — unlike the ledger).
BUDGETS_YAML_PATH = Path("app/data/budgets.yaml")


def load_budgets(path: Path = BUDGETS_YAML_PATH) -> list[Budget]:
    """Load monthly budget limits from config (spent is computed separately)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Budget.model_validate(entry) for entry in data.get("budgets", [])]


def compute_card_progress(cards: list[Card], ledger: list[Transaction]) -> list[Card]:
    """Return copies of `cards` with min_spend_progress_cents summed from the ledger.

    Progress = the sum of EXPENSES (positive amounts) charged to that card. Credits
    and other cards' spend do not count. This is what makes "you're $500 from the
    Amex bonus" a fact rather than a guess.
    """
    updated: list[Card] = []
    for card in cards:
        progress = sum(
            t.amount_cents
            for t in ledger
            if t.card_id == card.id and t.amount_cents > 0
        )
        updated.append(card.model_copy(update={"min_spend_progress_cents": progress}))
    return updated


def compute_budget_status(
    budgets: list[Budget],
    ledger: list[Transaction],
    month: tuple[int, int] | None = None,
) -> list[Budget]:
    """Return copies of `budgets` with spent_cents summed from the ledger.

    Args:
        month: optional (year, month) filter; when given, only transactions in that
            calendar month count. When None, all transactions count.
    """

    def _in_month(d: datetime.date) -> bool:
        return month is None or (d.year, d.month) == month

    updated: list[Budget] = []
    for budget in budgets:
        spent = sum(
            t.amount_cents
            for t in ledger
            if t.category == budget.category
            and t.amount_cents > 0
            and _in_month(t.txn_date)
        )
        updated.append(budget.model_copy(update={"spent_cents": spent}))
    return updated
