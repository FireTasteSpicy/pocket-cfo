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
from pathlib import Path

from app.models import CalendarEvent, CalendarEventType
from app.tools.aggregate import compute_card_progress
from app.tools.calendar_events import compute_money_dates
from app.tools.cards import load_cards
from app.tools.ledger import load_ledger

# calendar.events (not just .readonly) is required to CREATE events.
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

CLIENT_SECRET_PATH = Path("app/data/calendar_client_secret.json")
TOKEN_PATH = Path("app/data/calendar_token.json")

# Friendly titles per event type (kept out of the model's prompt — this is
# formatting, not reasoning).
_EVENT_TITLES: dict[CalendarEventType, str] = {
    CalendarEventType.PAYDAY: "\U0001f4b0 Payday",
    CalendarEventType.STATEMENT_CLOSE: "\U0001f4c4 Statement closes",
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


def get_calendar_service():
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


def create_event(service, event: CalendarEvent) -> dict:
    """Insert one CalendarEvent into the user's primary calendar. Returns the API response."""
    return (
        service.events().insert(calendarId="primary", body=event_body(event)).execute()
    )


def sync_money_dates_to_calendar() -> dict:
    """Create real Google Calendar events for the user's money-dates.

    Computes payday, payment-due, and each card's bonus-deadline events from the
    ledger and card terms (app/tools/calendar_events.py), then creates one
    all-day event per date via the live Calendar API. This is the ADK tool the
    Calendar agent calls for "add my money reminders" -- it is only attached to
    the agent when calendar_write_available() is true (see calendar_agent.py).

    Returns:
        {"synced": True, "count": int, "events": [...]} on success, or
        {"synced": False, "reason": str} if the one-time OAuth setup is missing.
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

    cards = compute_card_progress(load_cards(), load_ledger())
    events = compute_money_dates(cards)
    created = []
    for event in events:
        result = create_event(service, event)
        created.append(
            {
                "type": event.type.value,
                "date": event.date.isoformat(),
                "note": event.note,
                "html_link": result.get("htmlLink"),
            }
        )
    return {"synced": True, "count": len(created), "events": created}
