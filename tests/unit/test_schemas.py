"""Unit tests for the shared data schemas (app/models/schemas.py).

These are fast, deterministic, and need no API key — they pin the invariants the
rest of the system relies on: integer-cents money, the enum vocabularies, and the
tiny derived helpers the Card Strategy agent uses to score cards.
"""

import datetime

from app.models import (
    BonusCategory,
    Budget,
    CalendarEvent,
    CalendarEventType,
    Card,
    Transaction,
    TransactionSource,
)


# ── Transaction ─────────────────────────────────────────────────────────────
def test_transaction_defaults_are_safe() -> None:
    """A freshly built Transaction is UNredacted and uncategorized by default.

    This matters: `pii_redacted` must default to False so a record is never
    mistakenly treated as safe before the redaction step actually runs.
    """
    txn = Transaction(
        id="t1",
        merchant="Trader Joe's",
        amount_cents=4783,
        txn_date=datetime.date(2026, 7, 1),
        source=TransactionSource.RECEIPT,
    )
    assert txn.pii_redacted is False
    assert txn.reconciled is False
    assert txn.category is None
    assert txn.bonus_category is None
    assert txn.currency == "USD"
    assert txn.amount_cents == 4783  # positive == expense


def test_amount_sign_convention() -> None:
    """Negative amounts represent credits/income (used by injection-defense checks)."""
    refund = Transaction(
        id="t2",
        merchant="REFUND",
        amount_cents=-1500,
        txn_date=datetime.date(2026, 7, 2),
        source=TransactionSource.STATEMENT,
    )
    assert refund.amount_cents < 0


def test_str_enum_serializes_to_value() -> None:
    """StrEnum members stringify to their value (clean rationale text, clean JSON)."""
    assert str(BonusCategory.TRAVEL) == "TRAVEL"
    assert f"{BonusCategory.DINING}" == "DINING"
    txn = Transaction(
        id="t3",
        merchant="SQ *BLUE BOTTLE",
        amount_cents=650,
        txn_date=datetime.date(2026, 7, 3),
        source=TransactionSource.STATEMENT,
        bonus_category=BonusCategory.DINING,
    )
    # Round-trips through JSON as the plain value, not "BonusCategory.DINING".
    assert txn.model_dump(mode="json")["bonus_category"] == "DINING"


# ── Card helpers (the card-strategy building blocks) ────────────────────────
def _amex() -> Card:
    """An Amex with a $3,000 min-spend bonus, $2,500 progress, 3x travel."""
    return Card(
        id="amex_gold",
        name="Amex Gold",
        min_spend_target_cents=300_000,
        min_spend_progress_cents=250_000,
        bonus_deadline=datetime.date(2026, 7, 13),
        category_multipliers={
            BonusCategory.TRAVEL: 3.0,
            BonusCategory.DINING: 4.0,
            BonusCategory.DEFAULT: 1.0,
        },
    )


def test_card_open_bonus_and_remaining() -> None:
    card = _amex()
    assert card.has_open_bonus() is True
    assert card.min_spend_remaining_cents() == 50_000  # $500 to go


def test_card_bonus_met_closes() -> None:
    """Once progress meets the target, the bonus is no longer open."""
    card = _amex()
    card.min_spend_progress_cents = 300_000
    assert card.has_open_bonus() is False
    assert card.min_spend_remaining_cents() == 0


def test_card_no_bonus() -> None:
    """A card with no min-spend target never reports an open bonus."""
    plain = Card(id="visa", name="Everyday Visa")
    assert plain.has_open_bonus() is False
    assert plain.min_spend_remaining_cents() == 0


def test_multiplier_lookup_and_default_fallback() -> None:
    card = _amex()
    assert card.multiplier_for(BonusCategory.TRAVEL) == 3.0
    assert card.multiplier_for(BonusCategory.DINING) == 4.0
    # GROCERIES isn't listed -> falls back to DEFAULT (1.0), never raises.
    assert card.multiplier_for(BonusCategory.GROCERIES) == 1.0
    assert card.multiplier_for(None) == 1.0


# ── Budget helpers ──────────────────────────────────────────────────────────
def test_budget_remaining_and_over_limit() -> None:
    """$400 groceries budget, $310 spent -> $90 left; a $100 buy would breach it."""
    budget = Budget(
        category="Groceries", monthly_limit_cents=40_000, spent_cents=31_000
    )
    assert budget.remaining_cents() == 9_000
    assert budget.is_over_limit() is False
    assert budget.is_over_limit(prospective_cents=10_000) is True  # 310+100 > 400


# ── CalendarEvent ───────────────────────────────────────────────────────────
def test_calendar_event_types() -> None:
    ev = CalendarEvent(
        type=CalendarEventType.PAYMENT_DUE,
        date=datetime.date(2026, 8, 3),
        card_id="amex_gold",
        note="Amex payment due",
    )
    assert ev.type == CalendarEventType.PAYMENT_DUE
    assert ev.model_dump(mode="json")["type"] == "PAYMENT_DUE"
