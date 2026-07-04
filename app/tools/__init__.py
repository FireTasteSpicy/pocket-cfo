"""ADK tools and shared I/O helpers for Pocket CFO.

Tools are the ONLY way agents affect the world, so the read-only-by-design
guarantee is enforced here by construction: this package contains no function
that can move money. It holds:
  * redaction.py    — deterministic PII scrub (runs before any model call).
  * ledger.py       — read/write the local redacted ledger (JSON).
  * calendar_mcp.py — wiring to the Google Calendar MCP server (Phase 3).
Modules are added phase by phase.
"""
