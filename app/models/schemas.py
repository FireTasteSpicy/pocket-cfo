"""Data schemas for Pocket CFO — the durable contract every agent shares.

DESIGN (from SPEC.md §1):
  * Amounts are INTEGERS in the smallest currency unit (cents). Money is never a
    float here — floating-point drift is unacceptable in a finance ledger, and
    integer cents make reconciliation and budget math exact.
  * Structured, model-facing data uses Pydantic v2 so every agent validates the
    same shapes at its boundary (bad data fails loudly at the edge, not deep in a
    reasoning step).
  * `Transaction.pii_redacted` is the load-bearing security invariant: it MUST be
    true before a record leaves the ingestion boundary or is persisted. See
    `app/tools/redaction.py` and .agents/CONTEXT.md §2.

These types are intentionally pure data (plus a few tiny derived helpers). All
real logic — redaction, reconciliation, card scoring — lives in tested modules
that operate ON these types, never inside them.
"""

from __future__ import annotations

import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums — small, closed vocabularies shared across agents.
# ─────────────────────────────────────────────────────────────────────────────
class TransactionSource(StrEnum):
    """Where a Transaction came from. Drives dedup and trust decisions.

    STATEMENT and RECEIPT can describe the SAME purchase (settlement lag + tips),
    which is exactly what the statement-reconciler collapses into one record.
    MANUAL is conversational entry ("I spent $30 cash on lunch") — cash/PayNow
    spending that never hits a statement at all.
    """

    STATEMENT = "STATEMENT"
    RECEIPT = "RECEIPT"
    MANUAL = "MANUAL"


class BonusCategory(StrEnum):
    """The card-multiplier bucket a purchase falls into.

    This is the single hand-off between the Orchestrator's categorize_transaction
    and which_card tools: categorization maps a merchant to one of these, and the
    card strategist looks up each card's multiplier for it. DEFAULT is the catch-all
    (the "1x everything else" bucket).
    """

    TRAVEL = "TRAVEL"
    DINING = "DINING"
    GROCERIES = "GROCERIES"
    DEFAULT = "DEFAULT"


class CalendarEventType(StrEnum):
    """Kinds of money-dates the Calendar agent manages (SPEC.md §1)."""

    PAYDAY = "PAYDAY"
    PAYMENT_DUE = "PAYMENT_DUE"
    BONUS_DEADLINE = "BONUS_DEADLINE"


# ─────────────────────────────────────────────────────────────────────────────
# Core records
# ─────────────────────────────────────────────────────────────────────────────
class Transaction(BaseModel):
    """A single money movement in the redacted ledger.

    BEHAVIOR: `amount_cents` is positive for an expense and negative for a
    credit/income — so a naive prompt-injected "mark everything as income" would
    have to flip signs, which the numeric extraction path never does.
    """

    id: str = Field(..., description="Stable unique id for this transaction.")
    merchant: str = Field(..., description="Normalized merchant name.")
    amount_cents: int = Field(
        ..., description="Positive = expense, negative = credit/income. Cents."
    )
    currency: str = Field(default="USD", description='e.g. "USD", "SGD".')
    txn_date: datetime.date = Field(
        ..., description="Date on the receipt / when the purchase was made."
    )
    posted_date: datetime.date | None = Field(
        default=None,
        description="Date it settled on the statement (may lag txn_date).",
    )
    category: str | None = Field(
        default=None,
        description="Budget category (assigned by the categorize() engine).",
    )
    bonus_category: BonusCategory | None = Field(
        default=None,
        description="Card-multiplier bucket (assigned in the same pass).",
    )
    card_id: str | None = Field(
        default=None,
        description="Which card it was charged to; null for cash/manual entry.",
    )
    source: TransactionSource = Field(..., description="STATEMENT | RECEIPT | MANUAL.")
    reconciled: bool = Field(
        default=False,
        description="True once a receipt+statement pair has been merged into one.",
    )
    pii_redacted: bool = Field(
        default=False,
        description=(
            "SECURITY INVARIANT: must be true before this record leaves the "
            "ingestion boundary or is persisted. Set by the redaction step."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Optional itemized detail (e.g. kept from a merged receipt).",
    )


class Card(BaseModel):
    """A credit card's terms + live bonus progress (SPEC.md §1).

    The multipliers and min-spend terms are STATIC per card and live in the
    card-benefits reference skill (`.agents/skills/card-benefits/resources/
    cards.yaml`) so the model reads exact numbers instead of hallucinating them.
    `min_spend_progress_cents` is COMPUTED from the ledger, not stored by hand.
    """

    id: str
    name: str
    min_spend_target_cents: int | None = Field(
        default=None,
        description="Sign-up-bonus threshold; null = no active bonus.",
    )
    min_spend_progress_cents: int = Field(
        default=0, description="Computed from the ledger."
    )
    bonus_deadline: datetime.date | None = Field(
        default=None, description="When the minimum spend must be met by."
    )
    category_multipliers: dict[BonusCategory, float] = Field(
        default_factory=lambda: {BonusCategory.DEFAULT: 1.0},
        description="bonus_category -> points multiplier (must include DEFAULT).",
    )

    # ── tiny derived helpers (pure, no I/O) ─────────────────────────────────
    def has_open_bonus(self) -> bool:
        """True when the card still has an unmet minimum-spend bonus."""
        return (
            self.min_spend_target_cents is not None
            and self.min_spend_progress_cents < self.min_spend_target_cents
        )

    def min_spend_remaining_cents(self) -> int:
        """Cents still needed to clear the bonus (0 if none/already met)."""
        if self.min_spend_target_cents is None:
            return 0
        return max(0, self.min_spend_target_cents - self.min_spend_progress_cents)

    def multiplier_for(self, bonus_category: BonusCategory | None) -> float:
        """Points multiplier for a purchase in `bonus_category`.

        Falls back to the card's DEFAULT multiplier (or 1.0) when the category
        is unknown — never raises, so the card strategist can always score a card.
        """
        if bonus_category is None:
            bonus_category = BonusCategory.DEFAULT
        return self.category_multipliers.get(
            bonus_category, self.category_multipliers.get(BonusCategory.DEFAULT, 1.0)
        )


class Budget(BaseModel):
    """A monthly spend cap for one budget category (SPEC.md §1).

    `spent_cents` is computed from the ledger for the current month; it is the
    "actual" half of the budget-vs-actual view the concierge reports.
    """

    category: str
    monthly_limit_cents: int
    spent_cents: int = Field(default=0, description="Computed from the ledger.")

    def remaining_cents(self) -> int:
        """Headroom left this month (may go negative when over budget)."""
        return self.monthly_limit_cents - self.spent_cents

    def is_over_limit(self, prospective_cents: int = 0) -> bool:
        """True if spending `prospective_cents` more would breach the limit."""
        return (self.spent_cents + prospective_cents) > self.monthly_limit_cents


class CalendarEvent(BaseModel):
    """A money-date the Calendar agent creates in Google Calendar (SPEC.md §1)."""

    type: CalendarEventType
    date: datetime.date
    card_id: str | None = Field(default=None, description="Associated card, if any.")
    note: str = Field(default="", description="Human-readable reminder text.")
