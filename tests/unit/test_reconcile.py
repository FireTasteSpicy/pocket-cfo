"""Unit tests for receipt↔statement reconciliation (app/tools/reconcile.py).

Pins the two SPEC.md §3 reconciliation scenarios: MERGE a receipt with its
statement line despite settlement lag + a tip, and do NOT merge two genuinely
distinct purchases at the same merchant.
"""

from __future__ import annotations

import datetime

from app.models import Transaction, TransactionSource
from app.tools.reconcile import normalize_merchant, reconcile, same_purchase

_TUE = datetime.date(2026, 7, 7)
_THU = datetime.date(2026, 7, 9)  # settles 2 days later


def _receipt(
    amount_cents: int,
    merchant: str = "Trader Joe's",
    notes: str | None = "2x oat milk, bananas",
) -> Transaction:
    return Transaction(
        id=f"r-{amount_cents}",
        merchant=merchant,
        amount_cents=amount_cents,
        txn_date=_TUE,
        source=TransactionSource.RECEIPT,
        notes=notes,
        pii_redacted=True,
    )


def _statement(amount_cents: int, merchant: str = "TRADER JOE'S #123") -> Transaction:
    return Transaction(
        id=f"s-{amount_cents}",
        merchant=merchant,
        amount_cents=amount_cents,
        txn_date=_THU,
        posted_date=_THU,
        source=TransactionSource.STATEMENT,
        card_id="amex_gold",
        pii_redacted=True,
    )


# ── Merchant normalization ──────────────────────────────────────────────────
def test_normalize_merchant_ignores_case_punct_and_store_number() -> None:
    assert normalize_merchant("Trader Joe's") == normalize_merchant("TRADER JOE'S #123")
    assert normalize_merchant("SQ *BLUE BOTTLE COFFEE") >= {"BLUE", "BOTTLE"}


# ── SPEC: merge despite lag + tip ───────────────────────────────────────────
def test_merge_same_purchase_exact_amount() -> None:
    """Trader Joe's $47.83 receipt + statement line -> one reconciled record."""
    result = reconcile([_receipt(4783), _statement(4783)])
    assert len(result) == 1
    merged = result[0]
    assert merged.reconciled is True
    assert merged.notes == "2x oat milk, bananas"  # receipt's itemized detail kept
    assert merged.txn_date == _TUE  # real purchase date, not the settlement date
    assert merged.card_id == "amex_gold"  # statement's card retained


def test_merge_with_a_tip() -> None:
    """A 10% tip ($47.83 -> $52.61) still reconciles to one record."""
    result = reconcile([_receipt(4783), _statement(5261)])
    assert len(result) == 1
    assert result[0].reconciled is True


def test_same_purchase_predicate() -> None:
    assert same_purchase(_receipt(4783), _statement(4783)) is True
    assert same_purchase(_receipt(4783), _statement(8810)) is False


# ── SPEC: do NOT merge distinct purchases at the same merchant ──────────────
def test_do_not_merge_different_amounts() -> None:
    """$47.83 and $88.10 at the same merchant are two separate purchases."""
    result = reconcile([_receipt(4783), _statement(8810)])
    assert len(result) == 2
    assert all(t.reconciled is False for t in result)


def test_do_not_merge_different_merchant() -> None:
    result = reconcile(
        [
            _receipt(4783, merchant="Trader Joe's"),
            _statement(4783, merchant="WHOLE FOODS"),
        ]
    )
    assert len(result) == 2
    assert all(t.reconciled is False for t in result)


# ── Pass-through behavior ───────────────────────────────────────────────────
def test_manual_entries_pass_through() -> None:
    manual = Transaction(
        id="m1",
        merchant="Cash lunch",
        amount_cents=3000,
        txn_date=_TUE,
        source=TransactionSource.MANUAL,
    )
    result = reconcile([manual, _receipt(4783), _statement(4783)])
    ids = {t.id for t in result}
    assert "m1" in ids
    assert len(result) == 2  # manual + one merged record


def test_unmatched_receipt_survives() -> None:
    """A receipt with no matching statement is not silently dropped."""
    result = reconcile([_receipt(4783)])
    assert len(result) == 1
    assert result[0].source == TransactionSource.RECEIPT
