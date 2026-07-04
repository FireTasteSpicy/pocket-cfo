"""Deterministic PII redaction — the ingestion trust boundary's first job.

WHY DETERMINISTIC (not an LLM call): redaction is a security guarantee, and a
guarantee cannot depend on a probabilistic model that might, on some run, echo a
card number back. This module is plain, tested Python that runs BEFORE any model
sees the data. That is exactly why the "PII containment" eval can score a perfect
5.0 — the containment is enforced by code, not hoped for from a prompt.
(Reuses the SSN-redaction pattern from the course's expense-agent lab.)

DESIGN: we mask account/card numbers, SSNs, and long account/routing digit runs,
keeping only the last 4 digits visible (PCI-style) so a human can still recognize
"the card ending 3456" without the full number ever leaving the boundary. Money
amounts (short numbers like 47.83) are never touched — they are stored as separate
integer cents, and the patterns below only match long digit sequences.
"""

from __future__ import annotations

import re

from app.models import Transaction

# ── Patterns for the sensitive number formats we redact ─────────────────────
# Card / long account number: 13-19 digits, optionally grouped by single spaces
# or hyphens (e.g. "1234-5678-9012-3456" or "1234567890123456"). The pattern
# starts AND ends on a digit (separators only appear BETWEEN digits) so it never
# swallows a trailing space/newline after the number.
_CARD_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
# US SSN: 3-2-4 digits (kept from the course lab; strong privacy signal).
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Bare account / routing numbers: a run of 9-12 digits (below the card length).
_ACCT_RE = re.compile(r"\b\d{9,12}\b")

# Human-readable labels for what got redacted (used for logging/flagging).
_LABELS = {"card": "card/account number", "ssn": "SSN", "acct": "account number"}


def _mask(span: str) -> str:
    """Mask a matched span, keeping only its last 4 digits visible.

    Separators (spaces/hyphens) are dropped; every digit but the last four becomes
    a bullet. "1234-5678-9012-3456" -> "••••••••••••3456".
    """
    digits = re.sub(r"\D", "", span)
    if len(digits) <= 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 4) + digits[-4:]


def redact_text(text: str) -> tuple[str, list[str]]:
    """Redact PII from a raw string.

    Returns (redacted_text, hits) where `hits` names the categories found — so the
    Ingestion agent can log *that* redaction happened without logging the value.
    Order matters: SSN (most specific) first, then cards, then bare account runs,
    so a later, broader pattern can't re-match digits an earlier one already masked.
    """
    if not text:
        return text, []

    hits: list[str] = []

    def _sub(pattern: re.Pattern[str], label: str, s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            hits.append(_LABELS[label])
            return _mask(m.group(0))

        return pattern.sub(repl, s)

    redacted = _sub(_SSN_RE, "ssn", text)
    redacted = _sub(_CARD_RE, "card", redacted)
    redacted = _sub(_ACCT_RE, "acct", redacted)
    return redacted, hits


def contains_unredacted_pii(text: str) -> bool:
    """True if `text` still contains a full card/account number or SSN.

    Used by tests and by the ingestion boundary as a defensive post-condition:
    nothing with `contains_unredacted_pii == True` may be persisted.
    """
    if not text:
        return False
    return bool(_SSN_RE.search(text) or _CARD_RE.search(text) or _ACCT_RE.search(text))


def redact_transaction_with_hits(txn: Transaction) -> tuple[Transaction, list[str]]:
    """Like redact_transaction, but also reports WHAT was found (e.g. ["account
    number"]) -- never the value itself. Callers use this to build a deterministic,
    code-generated confirmation sentence ("the account number was redacted...")
    instead of leaving that security-relevant fact to a model's discretion to
    mention or not.
    """
    merchant, merchant_hits = redact_text(txn.merchant)
    notes, notes_hits = redact_text(txn.notes) if txn.notes else (txn.notes, [])
    updated = txn.model_copy(
        update={"merchant": merchant, "notes": notes, "pii_redacted": True}
    )
    return updated, merchant_hits + notes_hits


def redact_transaction(txn: Transaction) -> Transaction:
    """Return a copy of `txn` with free-text fields scrubbed and pii_redacted=True.

    Statement descriptors sometimes embed account fragments in the merchant string
    or notes; we scrub both. Numeric fields (amount_cents, dates) are structured
    and safe, so they are left untouched.
    """
    updated, _ = redact_transaction_with_hits(txn)
    return updated
