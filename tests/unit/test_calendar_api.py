"""Unit tests for the Calendar API fallback (app/tools/calendar_api.py).

Covers everything testable WITHOUT live Google credentials: the guarded
"no token yet" behavior (mirrors the MCP toolset's guarded pattern), the pure
event-body construction, and the dedicated-demo-calendar resolution logic
(create/reuse-by-name/reuse-cached, all against a fake service). Live event
creation itself needs a real OAuth token and is exercised manually via
scripts/calendar_oauth_setup.py + a live smoke test.
"""

from __future__ import annotations

import datetime
import json

import app.tools.calendar_api as calendar_api
from app.models import CalendarEvent, CalendarEventType
from app.tools.calendar_api import (
    create_event,
    event_body,
    get_or_create_demo_calendar_id,
)


class _FakeExecutable:
    """Mimics the googleapiclient `.execute()` call chain, success or failure."""

    def __init__(
        self, result: dict | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error

    def execute(self) -> dict:
        if self._error is not None:
            raise self._error
        return self._result


class _FakeEventsResource:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, dict]] = []

    def insert(self, calendarId: str, body: dict) -> _FakeExecutable:
        self.inserted.append((calendarId, body))
        return _FakeExecutable(
            {"id": "fake123", "htmlLink": "https://calendar.example/fake123"}
        )


class _FakeCalendarsResource:
    """Backs `service.calendars()` -- .get() (validate) and .insert() (create)."""

    def __init__(self, fail_get_for: frozenset[str] = frozenset()) -> None:
        self.fail_get_for = fail_get_for
        self.insert_calls: list[dict] = []

    def get(self, calendarId: str) -> _FakeExecutable:
        if calendarId in self.fail_get_for:
            return _FakeExecutable(error=RuntimeError("404 calendar not found"))
        return _FakeExecutable({"id": calendarId})

    def insert(self, body: dict) -> _FakeExecutable:
        new_id = f"generated-{len(self.insert_calls)}@group.calendar.google.com"
        self.insert_calls.append(body)
        return _FakeExecutable({"id": new_id, **body})


class _FakeCalendarListResource:
    """Backs `service.calendarList()` -- lists calendars the user already has."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items or []

    def list(self) -> _FakeExecutable:
        return _FakeExecutable({"items": self.items})


class _FakeCalendarService:
    """A minimal stand-in for the real Calendar v3 service object."""

    def __init__(
        self,
        calendar_list_items: list[dict] | None = None,
        fail_get_for: frozenset[str] = frozenset(),
    ) -> None:
        self.events_resource = _FakeEventsResource()
        self.calendars_resource = _FakeCalendarsResource(fail_get_for=fail_get_for)
        self.calendar_list_resource = _FakeCalendarListResource(calendar_list_items)

    def events(self) -> _FakeEventsResource:
        return self.events_resource

    def calendars(self) -> _FakeCalendarsResource:
        return self.calendars_resource

    def calendarList(self) -> _FakeCalendarListResource:
        return self.calendar_list_resource


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
    result = create_event(service, ev, calendar_id="some-demo-calendar")
    assert result["id"] == "fake123"
    calendar_id, body = service.events_resource.inserted[0]
    assert calendar_id == "some-demo-calendar"
    assert body["start"]["date"] == "2026-07-25"


def test_create_event_defaults_to_primary_if_unspecified() -> None:
    """The default only matters for direct/manual calls; sync always passes an id."""
    ev = CalendarEvent(type=CalendarEventType.PAYDAY, date=datetime.date(2026, 7, 25))
    service = _FakeCalendarService()
    create_event(service, ev)
    calendar_id, _ = service.events_resource.inserted[0]
    assert calendar_id == "primary"


# ── dedicated demo-calendar resolution (never "primary") ────────────────────
def test_creates_demo_calendar_when_none_exists(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "demo_id.json"
    monkeypatch.setattr(calendar_api, "_DEMO_CALENDAR_ID_CACHE", cache)
    service = _FakeCalendarService(calendar_list_items=[])  # nothing exists yet

    calendar_id = get_or_create_demo_calendar_id(service)

    assert calendar_id.endswith("@group.calendar.google.com")
    assert (
        service.calendars_resource.insert_calls[0]["summary"]
        == calendar_api.DEMO_CALENDAR_SUMMARY
    )
    # The new id is cached for next time.
    assert json.loads(cache.read_text())["calendar_id"] == calendar_id


def test_reuses_existing_calendar_found_by_name(tmp_path, monkeypatch) -> None:
    """No cache yet, but a 'Pocket CFO Demo' calendar already exists -> reuse it, don't recreate."""
    cache = tmp_path / "demo_id.json"
    monkeypatch.setattr(calendar_api, "_DEMO_CALENDAR_ID_CACHE", cache)
    service = _FakeCalendarService(
        calendar_list_items=[
            {"id": "existing-id", "summary": calendar_api.DEMO_CALENDAR_SUMMARY}
        ]
    )

    calendar_id = get_or_create_demo_calendar_id(service)

    assert calendar_id == "existing-id"
    assert service.calendars_resource.insert_calls == []  # never created a duplicate


def test_reuses_valid_cached_id_without_listing_calendars(
    tmp_path, monkeypatch
) -> None:
    cache = tmp_path / "demo_id.json"
    cache.write_text(json.dumps({"calendar_id": "cached-id"}), encoding="utf-8")
    monkeypatch.setattr(calendar_api, "_DEMO_CALENDAR_ID_CACHE", cache)
    service = _FakeCalendarService(
        calendar_list_items=[{"id": "other", "summary": "Unrelated"}]
    )

    calendar_id = get_or_create_demo_calendar_id(service)

    assert calendar_id == "cached-id"
    assert service.calendars_resource.insert_calls == []


def test_recreates_when_cached_id_no_longer_exists(tmp_path, monkeypatch) -> None:
    """A stale cache (calendar deleted by the user) falls through to create a fresh one."""
    cache = tmp_path / "demo_id.json"
    cache.write_text(json.dumps({"calendar_id": "deleted-id"}), encoding="utf-8")
    monkeypatch.setattr(calendar_api, "_DEMO_CALENDAR_ID_CACHE", cache)
    service = _FakeCalendarService(
        calendar_list_items=[], fail_get_for=frozenset({"deleted-id"})
    )

    calendar_id = get_or_create_demo_calendar_id(service)

    assert calendar_id != "deleted-id"
    assert len(service.calendars_resource.insert_calls) == 1


# ── sync_money_dates_to_calendar targets the demo calendar, never primary ───
def test_sync_writes_to_demo_calendar_not_primary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        calendar_api, "_DEMO_CALENDAR_ID_CACHE", tmp_path / "demo_id.json"
    )
    service = _FakeCalendarService(calendar_list_items=[])
    monkeypatch.setattr(calendar_api, "get_calendar_service", lambda: service)

    result = calendar_api.sync_money_dates_to_calendar()

    assert result["synced"] is True
    assert result["calendar_name"] == calendar_api.DEMO_CALENDAR_SUMMARY
    assert result["count"] == len(service.events_resource.inserted)
    for calendar_id, _ in service.events_resource.inserted:
        assert calendar_id != "primary"
