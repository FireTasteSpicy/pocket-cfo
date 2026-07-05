"""Unit test for the Google Calendar MCP toolset wiring (deterministic, no network).

The Calendar agent's marquee "clever tool use" is that it consumes Google's OFFICIAL
hosted Calendar MCP server through ADK's `McpToolset`. That wiring is only attached
when `GOOGLE_CALENDAR_MCP_ENDPOINT` is configured (so a clean checkout with no
Developer-Preview access still runs) — which otherwise leaves it un-exercised. This
test pins it offline: the builder returns a genuine `McpToolset` restricted to
exactly the four calendar-event tools (least privilege), or `None` when unset.
Construction does not open a connection, so no network or credentials are needed.
"""

from __future__ import annotations

from app.agents.calendar_agent import _DEFAULT_MCP_ENDPOINT, build_calendar_mcp_toolset

# The least-privilege allow-list the Calendar agent restricts the MCP server to.
_EXPECTED_FILTER = ["list_events", "create_event", "update_event", "delete_event"]


def _tool_filter(toolset: object) -> object:
    """Read the toolset's tool_filter across ADK versions (public or private attr)."""
    value = getattr(toolset, "tool_filter", None)
    return value if value is not None else getattr(toolset, "_tool_filter", None)


def test_no_mcp_toolset_when_endpoint_unset(monkeypatch) -> None:
    """Unconfigured: the builder returns None so the agent still runs on its
    reasoning-only tools (the guarded, clean-checkout-safe path)."""
    monkeypatch.delenv("GOOGLE_CALENDAR_MCP_ENDPOINT", raising=False)
    assert build_calendar_mcp_toolset() is None


def test_mcp_toolset_targets_official_server_with_least_privilege_filter(
    monkeypatch,
) -> None:
    """Configured: the builder returns a real ADK McpToolset (not a stub) scoped to
    exactly the four event tools it needs."""
    monkeypatch.setenv("GOOGLE_CALENDAR_MCP_ENDPOINT", _DEFAULT_MCP_ENDPOINT)
    toolset = build_calendar_mcp_toolset()
    assert toolset is not None

    from google.adk.tools.mcp_tool import McpToolset

    assert isinstance(toolset, McpToolset)
    assert _tool_filter(toolset) == _EXPECTED_FILTER
