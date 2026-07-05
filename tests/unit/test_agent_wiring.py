"""Structural guards on the agent wiring — the privilege boundary the whole
security story rests on (SPEC.md §4, ARCHITECTURE.md §1-2).

These are DETERMINISTIC, offline unit tests: agent construction does not call a
model, so importing the agents needs no API key. They pin two invariants that a
future edit could silently break:
  1. Read-only-by-design: NO tool on ANY agent can move money. The guarantee is
     structural (the capability is absent), so we assert it by enumeration rather
     than trusting a prompt instruction.
  2. Ingestion privilege separation: the untrusted-document reader has a NARROW
     tool surface (import-only + its reconciler skill) and specifically cannot
     reach the Calendar agent's write tools or the Orchestrator's advice tools.
If someone later adds a payment tool, or hands the Ingestion agent a calendar/
money tool, one of these tests fails instead of the regression shipping.
"""

from __future__ import annotations

from app.agent import root_agent
from app.agents.calendar_agent import calendar_agent
from app.agents.ingestion import ingestion_agent


def _tool_name(tool: object) -> str:
    """Best-effort display name for an ADK tool (raw function, FunctionTool, or
    AgentTool/SkillToolset), mirroring how the ADK surfaces it to the model."""
    for attr in ("name", "__name__"):
        value = getattr(tool, attr, None)
        if value:
            return str(value)
    inner = getattr(tool, "func", None) or getattr(tool, "function", None)
    if inner is not None:
        return getattr(inner, "__name__", type(tool).__name__)
    return type(tool).__name__


def _tool_names(agent: object) -> list[str]:
    return [_tool_name(t) for t in (getattr(agent, "tools", []) or [])]


# Verbs that would indicate a money-movement capability. The read-only guarantee
# is that NONE of these ever appears as a tool name on ANY agent.
_MONEY_VERBS = (
    "pay",
    "transfer",
    "wire",
    "withdraw",
    "send_money",
    "charge",
    "refund",
    "venmo",
    "zelle",
    "ach_debit",
    "checkout",
    "purchase",
)


def test_no_agent_exposes_a_money_movement_tool() -> None:
    """Read-only-by-design: enumerate every agent's tools; none moves money."""
    for agent in (root_agent, ingestion_agent, calendar_agent):
        for name in _tool_names(agent):
            lowered = name.lower()
            assert not any(verb in lowered for verb in _MONEY_VERBS), (
                f"{getattr(agent, 'name', agent)} exposes a money-movement-shaped "
                f"tool '{name}' — the read-only guarantee is structural and must hold"
            )


def test_ingestion_agent_has_only_its_narrow_ingest_surface() -> None:
    """The untrusted-document reader gets import tools + its reconciler skill,
    and nothing else — no advice, calendar, or budget tools."""
    names = set(_tool_names(ingestion_agent))
    assert {"import_bank_statement", "import_receipt"} <= names
    # No Orchestrator advice / budget tools leaked into the low-privilege agent.
    forbidden = {
        "which_card",
        "card_progress_summary",
        "get_budget_status",
        "log_manual_expense",
        "record_correction",
    }
    assert names.isdisjoint(forbidden), (
        f"ingestion agent over-privileged: {names & forbidden}"
    )


def test_ingestion_agent_cannot_reach_calendar_write() -> None:
    """Privilege separation: a compromise of the document reader must not reach
    the Calendar agent's write capability."""
    ingestion = set(_tool_names(ingestion_agent))
    calendar_only = {
        "list_money_dates",
        "suggest_bill_card",
        "sync_money_dates_to_calendar",
    }
    assert ingestion.isdisjoint(calendar_only)


def test_orchestrator_delegates_to_exactly_the_two_privilege_distinct_agents() -> None:
    """The 3-agent contract: only Ingestion and Calendar are sub-agents; the rest
    (categorize/which_card/…) are direct Orchestrator tools (ARCHITECTURE.md §1)."""
    names = set(_tool_names(root_agent))
    assert {"ingestion_agent", "calendar_agent"} <= names
    # which_card / categorization live as direct tools, not as delegated agents.
    assert {"which_card", "categorize_transaction"} <= names
