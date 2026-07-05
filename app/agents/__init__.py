"""Specialist agents for Pocket CFO.

Only the two agents whose SECURITY POSTURE differs from the Orchestrator's live
here; everything standard-privilege (categorization, the "which card?" call) runs
as a plain tool on the Orchestrator (app/agent.py), not as its own agent. The
modules here:
  * ingestion.py      — least-privilege document reader (restricted tool surface);
                        the ONLY agent that reads raw documents (parse -> redact
                        -> dedup). No calendar or money access.
  * calendar_agent.py — the only agent with calendar WRITE access (hosted Google
                        Calendar MCP server, or the GA REST fallback).

Both are wired into the Orchestrator in app/agent.py as AgentTools. (An earlier
revision also had categorization.py and card_strategy.py agents; both were
collapsed into direct Orchestrator tools because they need no privilege boundary
of their own — see app/agent.py.)
"""
