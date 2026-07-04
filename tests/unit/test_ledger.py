"""Unit tests for the ledger persistence guard (app/tools/ledger.py).

The guard is a security control: the ledger must NEVER contain an unredacted
record, and the write path enforces that structurally.
"""

from __future__ import annotations

import datetime

import pytest

from app.models import Transaction, TransactionSource
from app.tools.ledger import (
    UnredactedPersistError,
    append_transactions,
    load_ledger,
    save_ledger,
)

_DATE = datetime.date(2026, 7, 1)


def _safe_txn() -> Transaction:
    return Transaction(
        id="ok1",
        merchant="Trader Joe's",
        amount_cents=4783,
        txn_date=_DATE,
        source=TransactionSource.RECEIPT,
        pii_redacted=True,
    )


def test_round_trip_load_save(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    save_ledger([_safe_txn()], path)
    loaded = load_ledger(path)
    assert len(loaded) == 1
    assert loaded[0].merchant == "Trader Joe's"


def test_load_missing_ledger_returns_empty(tmp_path) -> None:
    assert load_ledger(tmp_path / "nope.json") == []


def test_guard_rejects_unredacted_flag(tmp_path) -> None:
    """A record with pii_redacted=False must not be persisted."""
    txn = _safe_txn().model_copy(update={"pii_redacted": False})
    with pytest.raises(UnredactedPersistError):
        save_ledger([txn], tmp_path / "ledger.json")


def test_guard_rejects_pii_in_text_even_if_flag_set(tmp_path) -> None:
    """Defense in depth: even if the flag lies, a full number is caught."""
    txn = _safe_txn().model_copy(
        update={"merchant": "ACCT 1234-5678-9012-3456", "pii_redacted": True}
    )
    with pytest.raises(UnredactedPersistError):
        save_ledger([txn], tmp_path / "ledger.json")


def test_append_accumulates(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    append_transactions([_safe_txn()], path)
    second = _safe_txn().model_copy(update={"id": "ok2"})
    full = append_transactions([second], path)
    assert len(full) == 2
    assert {t.id for t in full} == {"ok1", "ok2"}
