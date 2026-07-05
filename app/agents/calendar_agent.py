"""Calendar agent — money-date reminders via the Google Calendar MCP server.

PRIVILEGE (ARCHITECTURE.md §2.2): this is the one agent with calendar WRITE access.
That capability is exactly why it is a separate agent from Ingestion — their
security postures are incompatible, so a compromise of the document reader can't
reach calendar write. It has no access to raw documents and cannot move money.
This posture is architectural, not credential-dependent: Calendar is the only agent
ever wired with calendar-write tools, even on a clean checkout where no token is
present and those tools aren't attached (it then runs with reasoning-only tools).

MCP INTEGRATION (consumption over creation): the agent consumes Google's OFFICIAL
hosted Calendar MCP server (calendarmcp.googleapis.com) over streamable HTTP —
never a community server, per the course's security guidance. The connection is
built only when GOOGLE_CALENDAR_MCP_ENDPOINT is configured, so the module imports
cleanly with or without credentials. A google-api-python-client FunctionTool
(app/tools/calendar_api.py) is the live fallback for when Developer-Preview
access to the hosted MCP server isn't available: it writes real events via the
standard, GA Calendar v3 API using a plain OAuth "Desktop app" client — no
special program needed. Both write paths are attached only when their
credentials are actually present (see the guarded checks below); with neither
configured, the agent still works with its reasoning-only tools.

The agent's *reasoning* (which dates matter, and routing a bill to a card that
needs the spend) is deterministic and tested in app/tools/calendar_events.py; the
MCP server is only the write mechanism.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.tools.aggregate import compute_card_progress
from app.tools.calendar_api import (
    calendar_write_available,
    sync_money_dates_to_calendar,
)
from app.tools.calendar_events import compute_money_dates, suggest_bill_routing
from app.tools.cards import load_cards
from app.tools.ledger import load_ledger

_MODEL = "gemini-flash-latest"

# The official, Google-published hosted Calendar MCP endpoint (Developer Preview).
_DEFAULT_MCP_ENDPOINT = "https://calendarmcp.googleapis.com/mcp/v1"


# ── Deterministic reasoning tools (no calendar access needed) ───────────────
def list_money_dates() -> dict:
    """List the money-dates Pocket CFO tracks: payday, payment due, bonus deadlines.

    Returns:
        A dict {"events": [{type, date, note, card_id}]} sorted soonest-first.
    """
    cards = compute_card_progress(load_cards(), load_ledger())
    events = compute_money_dates(cards)
    return {
        "events": [
            {
                "type": e.type.value,
                "date": e.date.isoformat(),
                "note": e.note,
                "card_id": e.card_id,
            }
            for e in events
        ]
    }


def suggest_bill_card(bill_description: str, amount_dollars: float) -> dict:
    """Suggest which card to route an upcoming bill to, to help close a bonus.

    This is the "reason across dates" behavior: if a card's minimum-spend bonus is
    still open, paying a due bill with it makes progress on the bonus.

    Args:
        bill_description: What the bill is (e.g. "electricity bill").
        amount_dollars: The bill amount in dollars.

    Returns:
        A dict with a routing suggestion, or a note that no special routing is needed.
    """
    cards = compute_card_progress(load_cards(), load_ledger())
    suggestion = suggest_bill_routing(round(amount_dollars * 100), cards)
    if suggestion is None:
        return {
            "suggestion": None,
            "message": "No open bonus needs this spend — use your usual card.",
        }
    return {"bill": bill_description, "suggestion": suggestion}


# ── Official hosted Calendar MCP toolset (the write mechanism) ───────────────
def build_calendar_mcp_toolset():
    """Build an McpToolset for Google's hosted Calendar MCP server, or return None.

    Returns None (so the agent still works with its reasoning tools) unless
    GOOGLE_CALENDAR_MCP_ENDPOINT is set AND the mcp client is importable. The
    OAuth bearer token is injected per request from GOOGLE_CALENDAR_OAUTH_TOKEN,
    mirroring Google's ADK + Calendar-MCP codelab.
    """
    endpoint = os.environ.get("GOOGLE_CALENDAR_MCP_ENDPOINT")
    if not endpoint:
        return None
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StreamableHTTPConnectionParams,
        )
    except Exception:
        return None

    def _auth_header(_tool_context=None) -> dict:
        token = os.environ.get("GOOGLE_CALENDAR_OAUTH_TOKEN", "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=endpoint),
        header_provider=_auth_header,
        # Only the tools the Calendar agent needs (least privilege).
        tool_filter=["list_events", "create_event", "update_event", "delete_event"],
    )


# The agent's tools: always the deterministic reasoning tools, plus whichever
# live write mechanism is actually configured -- the hosted MCP server
# (Developer-Preview creds present) and/or the Calendar API fallback (a Desktop
# OAuth token present, via scripts/calendar_oauth_setup.py). Neither being
# configured is fine: the agent still works with reasoning-only tools.
_tools = [list_money_dates, suggest_bill_card]
_mcp_toolset = build_calendar_mcp_toolset()
if _mcp_toolset is not None:
    _tools.append(_mcp_toolset)
if calendar_write_available():
    _tools.append(sync_money_dates_to_calendar)


_CALENDAR_INSTRUCTION = (
    """
You are the Calendar agent for Pocket CFO. You manage the user's money-dates and
reason across them -- you do not just store dates.

- "What's coming up?" -> call `list_money_dates` and report the dates.
- "Add my money reminders to my calendar" / "sync my calendar" -> call
  `sync_money_dates_to_calendar` if it is available to actually create the events
  (payday, payment due, each card's bonus deadline) in the user's real calendar;
  report how many were created. If that tool isn't available, fall back to
  `list_money_dates` and explain the events aren't synced to a live calendar yet.
- When a bill is coming due, call `suggest_bill_card`. If an open card bonus needs
  the spend, suggest routing the bill to that card and say why -- e.g. "pay the
  electricity bill with the Amex to help close its minimum spend before the deadline".

You have calendar write access but you NEVER move money -- you remind, the user pays.
The official server you use is """
    + _DEFAULT_MCP_ENDPOINT
    + "."
).strip()


calendar_agent = Agent(
    name="calendar_agent",
    model=Gemini(model=_MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    description=(
        "Manages payday, payment-due, and bonus-deadline events via "
        "the Google Calendar MCP server, and reasons across them to nudge the user."
    ),
    instruction=_CALENDAR_INSTRUCTION,
    tools=_tools,
)
