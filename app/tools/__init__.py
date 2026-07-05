"""ADK tools and shared I/O helpers for Pocket CFO.

Tools are the ONLY way agents affect the world, so the read-only-by-design
guarantee is enforced here by construction: this package contains no function
that can move money. Key modules:
  * redaction.py       — deterministic PII scrub (runs before any model call).
  * injection_guard.py — deterministic prompt-injection detector for ingested text.
  * ingest.py          — parse -> scan -> redact -> reconcile -> persist pipeline.
  * ledger.py          — read/write the local redacted ledger, with a PII write-guard.
  * card_strategy.py   — the deterministic "which card?" decision logic.
  * calendar_api.py / calendar_events.py — GA Calendar REST fallback + money-date reasoning.
"""
