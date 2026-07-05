"""Google Calendar API fallback — live writes without Workspace Developer Preview.

WHY THIS EXISTS: the official hosted Google Calendar MCP server
(calendarmcp.googleapis.com, wired in app/agents/calendar_agent.py) requires
enrollment in the Google Workspace Developer Preview Program. This module is the
documented fallback (ARCHITECTURE.md §7): a thin wrapper over the standard, GA
Google Calendar API v3 (`googleapiclient`), authenticated with a plain OAuth
"Desktop app" client — no special program, just the ordinary Calendar API any
developer can enable on their own GCP project.

SECURITY: this is still the ONLY module with calendar write access (privilege
separation intact — Ingestion never imports this). Credentials are two local,
gitignored files, never hardcoded and never committed:
  * app/data/calendar_client_secret.json — the OAuth client YOU download from
    Cloud Console (a per-project secret, not a Pocket CFO secret).
  * app/data/calendar_token.json — the refresh token produced by the one-time
    consent flow (scripts/calendar_oauth_setup.py).
Both paths are absent on a clean checkout, so `get_calendar_service()` returns
None and the Calendar agent falls back to reasoning-only tools — the same
guarded pattern used for the MCP toolset (see build_calendar_mcp_toolset in
app/agents/calendar_agent.py).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.models import CalendarEvent, CalendarEventType
from app.tools.aggregate import compute_card_progress
from app.tools.calendar_events import compute_money_dates
from app.tools.cards import load_cards
from app.tools.ledger import load_ledger

if TYPE_CHECKING:
    # For annotations only: the googleapiclient Calendar service type. It is
    # imported lazily inside get_calendar_service() at runtime, so this block never
    # executes then (and `from __future__ import annotations` keeps the hints lazy).
    from googleapiclient.discovery import Resource

# The full "calendar" scope (not just .events) is required: creating/listing the
# dedicated "Pocket CFO Demo" calendar itself (calendars().insert/calendarList())
# needs calendar-management permission, which the narrower calendar.events scope
# (event CRUD only) does not grant.
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

CLIENT_SECRET_PATH = Path("app/data/calendar_client_secret.json")
TOKEN_PATH = Path("app/data/calendar_token.json")

# Pocket CFO writes to its OWN secondary calendar, never the user's primary one --
# demo events (or any accidental double-run) stay out of the user's real schedule
# and are trivially removable (delete the calendar, not individual events). Google
# Calendar has no "category" concept within a calendar; a separate calendar IS the
# mechanism the API exposes for this. The id is cached after first creation so
# repeated runs reuse the same calendar instead of creating duplicates.
DEMO_CALENDAR_SUMMARY = "Pocket CFO Demo"
_DEMO_CALENDAR_ID_CACHE = Path("app/data/calendar_demo_id.json")

# Friendly titles per event type (kept out of the model's prompt — this is
# formatting, not reasoning).
_EVENT_TITLES: dict[CalendarEventType, str] = {
    CalendarEventType.PAYDAY: "\U0001f4b0 Payday",
    CalendarEventType.PAYMENT_DUE: "\U0001f4b3 Card payment due",
    CalendarEventType.BONUS_DEADLINE: "\U0001f3af Card sign-up-bonus deadline",
}


def calendar_write_available() -> bool:
    """Cheap, local check: has the one-time OAuth consent already been done?

    Only checks for the token file's existence (no network call) so it is safe
    to call at agent-construction time to decide whether to attach the live
    write tool, mirroring build_calendar_mcp_toolset's env-var check.
    """
    return TOKEN_PATH.exists()


def get_calendar_service() -> Resource | None:
    """Return an authorized Calendar v3 service, or None if not yet configured.

    Refreshes an expired access token using the cached refresh token (no user
    interaction needed after the initial consent). Returns None -- never raises
    -- when the token file is missing or the client libraries aren't installed,
    so importing this module is always safe.
    """
    if not TOKEN_PATH.exists():
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), CALENDAR_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def event_body(event: CalendarEvent) -> dict:
    """Build the Calendar API request body for one CalendarEvent (pure, testable).

    All-day event: 'end.date' is exclusive per the Calendar API, so it is the day
    AFTER the event date.
    """
    title = _EVENT_TITLES.get(event.type, event.type.value.replace("_", " ").title())
    end_date = event.date + datetime.timedelta(days=1)
    return {
        "summary": title,
        "description": event.note or title,
        "start": {"date": event.date.isoformat()},
        "end": {"date": end_date.isoformat()},
    }


def create_event(
    service: Resource, event: CalendarEvent, calendar_id: str = "primary"
) -> dict:
    """Insert one CalendarEvent into `calendar_id`. Returns the API response.

    Defaults to "primary" only for callers that explicitly want that (e.g. a
    quick manual test); sync_money_dates_to_calendar always passes the dedicated
    demo calendar's id explicitly.
    """
    return (
        service.events()
        .insert(calendarId=calendar_id, body=event_body(event))
        .execute()
    )


def get_or_create_demo_calendar_id(service: Resource) -> str:
    """Return the id of Pocket CFO's dedicated "Pocket CFO Demo" calendar.

    Order of preference: (1) a cached id from a prior run, verified still valid;
    (2) an existing calendar with the right name (in case the cache was lost but
    the calendar wasn't); (3) create it fresh. Never returns "primary" -- this is
    the whole point of keeping demo events off the user's real calendar.
    """
    if _DEMO_CALENDAR_ID_CACHE.exists():
        cached_id = json.loads(_DEMO_CALENDAR_ID_CACHE.read_text()).get("calendar_id")
        if cached_id:
            try:
                service.calendars().get(calendarId=cached_id).execute()
                return cached_id
            except Exception:
                pass

    existing = service.calendarList().list().execute()
    for entry in existing.get("items", []):
        if entry.get("summary") == DEMO_CALENDAR_SUMMARY:
            _cache_demo_calendar_id(entry["id"])
            return entry["id"]

    created = (
        service.calendars()
        .insert(
            body={
                "summary": DEMO_CALENDAR_SUMMARY,
                "description": "Money-date reminders created by the Pocket CFO Calendar agent.",
            }
        )
        .execute()
    )
    _cache_demo_calendar_id(created["id"])
    return created["id"]


def _cache_demo_calendar_id(calendar_id: str) -> None:
    _DEMO_CALENDAR_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _DEMO_CALENDAR_ID_CACHE.write_text(
        json.dumps({"calendar_id": calendar_id}), encoding="utf-8"
    )


def sync_money_dates_to_calendar() -> dict:
    """Create real Google Calendar events for the user's money-dates.

    Computes payday, payment-due, and each card's bonus-deadline events from the
    ledger and card terms (app/tools/calendar_events.py), then creates one
    all-day event per date in Pocket CFO's OWN "Pocket CFO Demo" calendar --
    never the user's primary calendar. This is the ADK tool the Calendar agent
    calls for "add my money reminders" -- it is only attached to the agent when
    calendar_write_available() is true (see calendar_agent.py).

    Returns:
        {"synced": True, "count": int, "calendar_name": str, "events": [...]} on
        success, or {"synced": False, "reason": str} if the one-time OAuth setup
        is missing.
    """
    service = get_calendar_service()
    if service is None:
        return {
            "synced": False,
            "reason": (
                "Calendar isn't connected yet. Run the one-time setup once: "
                "uv run python scripts/calendar_oauth_setup.py"
            ),
        }

    calendar_id = get_or_create_demo_calendar_id(service)
    cards = compute_card_progress(load_cards(), load_ledger())
    events = compute_money_dates(cards)
    created = []
    for event in events:
        result = create_event(service, event, calendar_id=calendar_id)
        created.append(
            {
                "type": event.type.value,
                "date": event.date.isoformat(),
                "note": event.note,
                "html_link": result.get("htmlLink"),
            }
        )
    return {
        "synced": True,
        "count": len(created),
        "calendar_name": DEMO_CALENDAR_SUMMARY,
        "events": created,
    }
