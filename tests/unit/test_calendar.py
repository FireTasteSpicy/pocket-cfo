"""Unit tests for the Calendar agent's reasoning core (app/tools/calendar_events.py).

Covers SPEC.md §3 "Calendar reminders" — creating money-date events — and "Reason
across dates" — suggesting a bill be routed to a card whose bonus needs the spend.
"""

from __future__ import annotations

import datetime

from app.models import CalendarEventType
from app.tools.calendar_events import compute_money_dates, suggest_bill_routing
from app.tools.cards import load_cards

_TODAY = datetime.date(2026, 7, 4)


def test_compute_money_dates_includes_payday_payment_and_bonus() -> None:
    cards = load_cards()  # amex_gold has an active bonus with a deadline
    events = compute_money_dates(cards, payday_day=25, payment_due_day=3, today=_TODAY)
    types = {e.type for e in events}
    assert CalendarEventType.PAYDAY in types
    assert CalendarEventType.PAYMENT_DUE in types
    assert CalendarEventType.BONUS_DEADLINE in types
    # Events are sorted soonest-first.
    dates = [e.date for e in events]
    assert dates == sorted(dates)
    # The Amex bonus deadline is on the card's date.
    bonus = next(e for e in events if e.type is CalendarEventType.BONUS_DEADLINE)
    assert bonus.card_id == "amex_gold"
    assert bonus.date == datetime.date(2026, 7, 13)


def test_payday_and_payment_roll_to_next_valid_occurrence() -> None:
    events = compute_money_dates([], payday_day=25, payment_due_day=3, today=_TODAY)
    payday = next(e for e in events if e.type is CalendarEventType.PAYDAY)
    payment = next(e for e in events if e.type is CalendarEventType.PAYMENT_DUE)
    assert payday.date == datetime.date(2026, 7, 25)  # the 25th is still ahead
    assert payment.date == datetime.date(
        2026, 8, 3
    )  # the 3rd already passed -> next month


def test_suggest_bill_routing_to_open_bonus_card() -> None:
    """SPEC: bill due + Amex minimum short -> suggest routing it to the Amex."""
    cards = load_cards()  # amex_gold has an open, live bonus (progress 0 < target)
    suggestion = suggest_bill_routing(40_000, cards, today=_TODAY)  # a $400 bill
    assert suggestion is not None
    assert suggestion["suggested_card_id"] == "amex_gold"
    assert "american express" in suggestion["suggested_card_name"].lower()


def test_no_suggestion_when_no_open_bonus() -> None:
    cards = [c for c in load_cards() if c.id != "amex_gold"]  # drop the only bonus card
    assert suggest_bill_routing(40_000, cards, today=_TODAY) is None
