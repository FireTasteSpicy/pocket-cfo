"""Unit tests for ledger aggregation (app/tools/aggregate.py) + a full hero
end-to-end that exercises the whole deterministic chain from seed data to the
which-card recommendation, with no API key required.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from app.models import BonusCategory, Budget, Card, Transaction, TransactionSource
from app.tools.aggregate import compute_budget_status, compute_card_progress
from app.tools.card_strategy import DecidingFactor, recommend_card
from app.tools.cards import get_card, load_cards
from app.tools.categorize import categorize
from app.tools.ingest import ingest_statement_csv
from app.tools.ledger import load_ledger


def _txn(**kw) -> Transaction:
    base = {
        "id": "t",
        "merchant": "M",
        "amount_cents": 1000,
        "txn_date": datetime.date(2026, 6, 15),
        "source": TransactionSource.STATEMENT,
        "pii_redacted": True,
    }
    base.update(kw)
    return Transaction(**base)


# ── card progress ───────────────────────────────────────────────────────────
def test_card_progress_sums_only_expenses_on_that_card() -> None:
    cards = [Card(id="amex", name="Amex", min_spend_target_cents=300_000)]
    ledger = [
        _txn(id="1", card_id="amex", amount_cents=100_000),
        _txn(id="2", card_id="amex", amount_cents=150_000),
        _txn(id="3", card_id="other", amount_cents=99_999),  # different card
        _txn(id="4", card_id="amex", amount_cents=-5_000),  # a credit, not spend
    ]
    updated = compute_card_progress(cards, ledger)
    assert updated[0].min_spend_progress_cents == 250_000
    assert updated[0].min_spend_remaining_cents() == 50_000


# ── budget status ───────────────────────────────────────────────────────────
def test_budget_status_sums_by_category_and_month() -> None:
    budgets = [Budget(category="Groceries", monthly_limit_cents=40_000)]
    ledger = [
        _txn(
            id="1",
            category="Groceries",
            amount_cents=31_000,
            txn_date=datetime.date(2026, 6, 3),
        ),
        _txn(
            id="2",
            category="Dining",
            amount_cents=5_000,
            txn_date=datetime.date(2026, 6, 4),
        ),
        _txn(
            id="3",
            category="Groceries",
            amount_cents=10_000,
            txn_date=datetime.date(2026, 5, 9),
        ),
    ]
    updated = compute_budget_status(budgets, ledger, month=(2026, 6))
    assert updated[0].spent_cents == 31_000  # SPEC: $310 of $400
    assert updated[0].remaining_cents() == 9_000  # $90 remaining


# ── FULL HERO END-TO-END (deterministic, no model) ─────────────────────────
def test_hero_end_to_end_from_seed(tmp_path) -> None:
    """Ingest the seed statement -> $2,500 on the Amex -> 'which card for a flight?'
    -> recommend the Amex because it clears the $3,000 minimum. This is the demo
    centerpiece proven end-to-end without any API call."""
    ledger_path = tmp_path / "ledger.json"
    csv = Path("app/data/seed/sample_statement.csv").read_text()

    # 1. Ingest the statement onto the Amex (redacts + records 18 transactions).
    ingest_statement_csv(csv, card_id="amex_gold", ledger_path=ledger_path)
    ledger = load_ledger(ledger_path)

    # 2. Card progress is computed from the ledger: exactly $2,500 toward $3,000.
    cards = compute_card_progress(load_cards(), ledger)
    amex = get_card(cards, "amex_gold")
    assert amex.min_spend_progress_cents == 250_000
    assert amex.min_spend_remaining_cents() == 50_000

    # 3. Categorize the prospective purchase phrase.
    _, bonus_category = categorize("a $500 flight")
    assert bonus_category is BonusCategory.TRAVEL

    # 4. The hero recommendation.
    rec = recommend_card(50_000, bonus_category, cards, today=datetime.date(2026, 7, 4))
    assert rec.card_id == "amex_gold"
    assert rec.deciding_factor is DecidingFactor.BONUS_GAP
    assert "clears your $3,000 minimum with 9 days to spare" in rec.rationale
