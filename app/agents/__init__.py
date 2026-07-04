"""Specialist agents for Pocket CFO.

Each module here defines one ADK agent with a specific privilege posture:
  * ingestion.py      — sandboxed, low-privilege; the ONLY agent that reads raw
                        documents (parse -> redact -> dedup).
  * categorization.py — standard; assigns budget + bonus category in one pass.
  * card_strategy.py  — standard; the "which card?" hero recommender.
  * calendar_agent.py — calendar write-access via the Google Calendar MCP server.

They are wired together through the Orchestrator in app/agent.py. Modules are
added phase by phase; this package marker keeps `app.agents.*` importable.
"""
