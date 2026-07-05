"""Money-date reasoning for the Calendar agent (deterministic core).

The Calendar agent doesn't just STORE dates — it reasons across them (SPEC.md §3
"Reason across dates, not just store them"). This module computes the money-dates
from the ledger + card terms, and produces the cross-date suggestion that makes the
feature more than a reminder list: "this bill is due soon AND a card bonus is short
— route the bill to that card." The agent then creates the events via its calendar
write tool (the hosted Calendar MCP server when configured, else the GA Calendar
REST fallback); the reasoning here is testable without any calendar access.
"""

from __future__ import annotations

import datetime

from app.models import BonusCategory, CalendarEvent, CalendarEventType, Card


def _next_day_of_month(today: datetime.date, day: int) -> datetime.date:
    """The next date whose day-of-month is `day` (this month, else next month)."""
    day = min(day, 28)  # keep it valid in every month
    candidate = today.replace(day=day)
    if candidate < today:
        # roll to next month
        year, month = (today.year, today.month + 1)
        if month > 12:
            year, month = year + 1, 1
        candidate = datetime.date(year, month, day)
    return candidate


def compute_money_dates(
    cards: list[Card],
    payday_day: int = 25,
    payment_due_day: int = 3,
    today: datetime.date | None = None,
) -> list[CalendarEvent]:
    """Derive the reminder events Pocket CFO should put on the calendar.

    Produces a PAYDAY, a card PAYMENT_DUE, and a BONUS_DEADLINE per card that has an
    active minimum-spend bonus. Returned sorted by date (soonest first).
    """
    today = today or datetime.date.today()
    events: list[CalendarEvent] = [
        CalendarEvent(
            type=CalendarEventType.PAYDAY,
            date=_next_day_of_month(today, payday_day),
            note="Payday",
        ),
        CalendarEvent(
            type=CalendarEventType.PAYMENT_DUE,
            date=_next_day_of_month(today, payment_due_day),
            note="Credit-card payment due",
        ),
    ]
    for card in cards:
        if card.bonus_deadline is not None and card.min_spend_target_cents is not None:
            events.append(
                CalendarEvent(
                    type=CalendarEventType.BONUS_DEADLINE,
                    date=card.bonus_deadline,
                    card_id=card.id,
                    note=f"{card.name} sign-up-bonus deadline",
                )
            )
    return sorted(events, key=lambda e: e.date)


def suggest_bill_routing(
    bill_amount_cents: int,
    cards: list[Card],
    today: datetime.date | None = None,
) -> dict | None:
    """Given an upcoming bill, suggest routing it to a card that needs the spend.

    Returns a suggestion dict when a card has a live minimum-spend bonus this bill
    would help close, else None (no bonus pressure -> no special routing needed).
    This is the "reason across dates" behavior: the bill's due date and the bonus's
    deadline are considered together.
    """
    today = today or datetime.date.today()
    # Reuse the hero decision logic (a bill is DEFAULT-category spend).
    from app.tools.card_strategy import recommend_card

    live_bonus = [
        c
        for c in cards
        if c.has_open_bonus()
        and c.bonus_deadline is not None
        and (c.bonus_deadline - today).days >= 0
    ]
    if not live_bonus:
        return None

    rec = recommend_card(bill_amount_cents, BonusCategory.DEFAULT, cards, today=today)
    return {
        "suggested_card_id": rec.card_id,
        "suggested_card_name": rec.card_name,
        "rationale": rec.rationale,
    }
