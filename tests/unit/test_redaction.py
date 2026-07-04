"""Unit tests for PII redaction (app/tools/redaction.py).

These pin the SPEC.md §3 "PII redaction (security)" scenario as deterministic,
API-key-free tests. This is the security invariant that must never regress, so it
is tested at the code level (not only via the LLM-as-judge eval).
"""

from __future__ import annotations

import datetime

from app.models import Transaction, TransactionSource
from app.tools.redaction import (
    contains_unredacted_pii,
    redact_text,
    redact_transaction,
)

# The exact account number from the SPEC scenario.
_ACCOUNT = "1234-5678-9012-3456"


def test_redacts_account_number_keeping_last_four() -> None:
    """SPEC: a statement line's account number is masked; no full number remains."""
    line = f"ACH DEBIT ACCT {_ACCOUNT} AUTOPAY"
    redacted, hits = redact_text(line)
    assert "1234-5678-9012-3456" not in redacted
    assert "1234567890123456" not in redacted
    assert "3456" in redacted  # last 4 kept for human recognition (PCI-style)
    assert hits  # something was flagged as redacted
    assert not contains_unredacted_pii(redacted)


def test_contains_unredacted_pii_detects_before_and_clears_after() -> None:
    assert contains_unredacted_pii(f"card {_ACCOUNT}") is True
    redacted, _ = redact_text(f"card {_ACCOUNT}")
    assert contains_unredacted_pii(redacted) is False


def test_card_number_without_separators_is_masked() -> None:
    redacted, _ = redact_text("charge on 4111111111111111 today")
    assert "4111111111111111" not in redacted
    assert redacted.endswith("1111 today")


def test_ssn_is_redacted() -> None:
    redacted, hits = redact_text("SSN 123-45-6789 on file")
    assert "123-45-6789" not in redacted
    assert "SSN" in "".join(hits)


def test_money_amounts_are_never_touched() -> None:
    """Amounts are short numbers and must survive redaction verbatim."""
    redacted, hits = redact_text("Trader Joe's $47.83 on 2026-07-01")
    assert "47.83" in redacted
    assert hits == []  # nothing looked like PII


def test_redact_transaction_sets_flag_and_scrubs_fields() -> None:
    """SPEC: the resulting Transaction has pii_redacted=true and no full number."""
    txn = Transaction(
        id="s1",
        merchant=f"BANK TRANSFER {_ACCOUNT}",
        amount_cents=10_000,
        txn_date=datetime.date(2026, 7, 1),
        source=TransactionSource.STATEMENT,
        notes=f"linked account {_ACCOUNT}",
    )
    assert txn.pii_redacted is False  # unsafe until redaction runs
    safe = redact_transaction(txn)
    assert safe.pii_redacted is True
    assert not contains_unredacted_pii(safe.merchant)
    assert not contains_unredacted_pii(safe.notes or "")
    assert safe.amount_cents == 10_000  # structured numeric field untouched
