"""Unit tests for the Calendar API fallback (app/tools/calendar_api.py).

Covers everything testable WITHOUT live Google credentials: the guarded
"no token yet" behavior (mirrors the MCP toolset's guarded pattern) and the pure
event-body construction. Live event creation itself needs a real OAuth token and
is exercised manually via scripts/calendar_oauth_setup.py + a live smoke test.
"""

from __future__ import annotations

import datetime

import app.tools.calendar_api as calendar_api
from app.models import CalendarEvent, CalendarEventType
from app.tools.calendar_api import create_event, event_body


class _FakeExecutable:
    """Mimics the googleapiclient `.execute()` call chain."""

    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self) -> dict:
        return self._result


class _FakeEventsResource:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, dict]] = []

    def insert(self, calendarId: str, body: dict) -> _FakeExecutable:
        self.inserted.append((calendarId, body))
        return _FakeExecutable(
            {"id": "fake123", "htmlLink": "https://calendar.example/fake123"}
        )


class _FakeCalendarService:
    """A minimal stand-in for the real Calendar v3 service object."""

    def __init__(self) -> None:
        self.events_resource = _FakeEventsResource()

    def events(self) -> _FakeEventsResource:
        return self.events_resource


# ── guarded "not configured yet" behavior ───────────────────────────────────
def test_calendar_write_unavailable_without_token(tmp_path, monkeypatch) -> None:
    """No token file -> both the availability check and the service builder are safe."""
    monkeypatch.setattr(calendar_api, "TOKEN_PATH", tmp_path / "nope.json")
    assert calendar_api.calendar_write_available() is False
    assert calendar_api.get_calendar_service() is None


def test_sync_without_token_reports_setup_instructions(tmp_path, monkeypatch) -> None:
    """SPEC: never fail silently -- explain the one-time setup that's missing."""
    monkeypatch.setattr(calendar_api, "TOKEN_PATH", tmp_path / "nope.json")
    result = calendar_api.sync_money_dates_to_calendar()
    assert result["synced"] is False
    assert "calendar_oauth_setup.py" in result["reason"]


# ── pure event-body construction (no network) ───────────────────────────────
def test_event_body_shape_and_exclusive_end_date() -> None:
    ev = CalendarEvent(
        type=CalendarEventType.PAYMENT_DUE,
        date=datetime.date(2026, 7, 10),
        card_id="amex_gold",
        note="Amex payment due",
    )
    body = event_body(ev)
    assert body["start"]["date"] == "2026-07-10"
    # All-day events use an EXCLUSIVE end date per the Calendar API -> +1 day.
    assert body["end"]["date"] == "2026-07-11"
    assert "payment" in body["summary"].lower()
    assert body["description"] == "Amex payment due"


def test_event_body_falls_back_to_title_without_notes() -> None:
    ev = CalendarEvent(type=CalendarEventType.PAYDAY, date=datetime.date(2026, 7, 25))
    body = event_body(ev)
    assert body["description"] == body["summary"]  # no note -> description = title


# ── create_event against a fake service (no real API call) ─────────────────
def test_create_event_calls_insert_with_correct_body() -> None:
    ev = CalendarEvent(
        type=CalendarEventType.PAYDAY, date=datetime.date(2026, 7, 25), note="Payday"
    )
    service = _FakeCalendarService()
    result = create_event(service, ev)
    assert result["id"] == "fake123"
    calendar_id, body = service.events_resource.inserted[0]
    assert calendar_id == "primary"
    assert body["start"]["date"] == "2026-07-25"
