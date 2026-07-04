"""Receipt ↔ statement reconciliation — the dedup logic (SPEC.md §3).

THE PROBLEM (why an agent needs this at all): a receipt says "$47.83, Trader
Joe's, Tuesday"; the bank statement shows "TRADER JOE'S #123  $47.83" posting on
*Thursday* (settlement lag), and if you tipped, the amounts won't even match. A
naive matcher double-counts the purchase or misses it. This module recognizes the
two lines as the SAME purchase and collapses them into one enriched record — while
NOT merging two genuinely distinct purchases at the same merchant.

DESIGN: deterministic and tested (not an LLM guess), so budget totals and
min-spend progress are exact. The Ingestion agent calls it as a tool; the
statement-reconciler skill (.agents/skills/statement-reconciler/) documents the
policy and wraps this module.

Matching rule — a RECEIPT and a STATEMENT line are the same purchase when:
  1. merchant tokens match (case/punctuation/store-number insensitive), AND
  2. the statement amount is within a tip tolerance of the receipt amount
     (equal, or up to +25% for a tip — never a wildly different amount), AND
  3. the statement posted within a few days of the receipt date (settlement lag).
"""

from __future__ import annotations

import datetime
import re

from app.models import Transaction, TransactionSource

# Tunable thresholds (documented so they are a deliberate policy, not magic).
_MAX_LAG_DAYS = 5  # statements usually settle within a few days of purchase
_TIP_TOLERANCE_PCT = 0.25  # a tip can add up to ~25%; beyond that it's a diff buy
_ROUNDING_SLACK_CENTS = 1  # tolerate a 1-cent rounding wobble below the receipt


def normalize_merchant(name: str) -> set[str]:
    """Reduce a merchant string to a set of comparable tokens.

    Uppercases, strips punctuation and "#123" store numbers, and splits into
    words. "Trader Joe's" and "TRADER JOE'S #123" both -> {"TRADER", "JOES"}.
    """
    upper = name.upper()
    upper = re.sub(r"#\s*\d+", " ", upper)  # drop store numbers like "#123"
    upper = re.sub(r"[^A-Z0-9 ]", "", upper)  # drop punctuation (apostrophes etc.)
    # Drop common payment-processor prefixes that add noise (e.g. "SQ *").
    tokens = {t for t in upper.split() if t and t not in {"SQ", "TST", "POS"}}
    return tokens


def _merchants_match(a: str, b: str) -> bool:
    """True if two merchant strings plausibly name the same merchant.

    Uses token subset: the smaller token set must be fully contained in the
    larger (and non-empty). This handles "BLUE BOTTLE" vs "SQ *BLUE BOTTLE COFFEE".
    """
    ta, tb = normalize_merchant(a), normalize_merchant(b)
    if not ta or not tb:
        return False
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return smaller.issubset(larger)


def _amounts_match(receipt_cents: int, statement_cents: int) -> bool:
    """True if the statement amount is the receipt amount, plus at most a tip."""
    low = receipt_cents - _ROUNDING_SLACK_CENTS
    high = receipt_cents + round(receipt_cents * _TIP_TOLERANCE_PCT)
    return low <= statement_cents <= high


def _dates_match(
    receipt_date: datetime.date, posted_date: datetime.date | None
) -> bool:
    """True if the statement posted within the settlement-lag window."""
    if posted_date is None:
        return True  # no posted date to contradict a match
    lag = (posted_date - receipt_date).days
    return -1 <= lag <= _MAX_LAG_DAYS


def same_purchase(receipt: Transaction, statement: Transaction) -> bool:
    """Do a receipt and a statement line describe the same purchase?"""
    return (
        _merchants_match(receipt.merchant, statement.merchant)
        and _amounts_match(receipt.amount_cents, statement.amount_cents)
        and _dates_match(receipt.txn_date, statement.posted_date)
    )


def _merge(receipt: Transaction, statement: Transaction) -> Transaction:
    """Collapse a matched receipt+statement pair into one enriched record.

    We keep the STATEMENT's authoritative charged amount, posted_date and card_id
    (what actually hit the account, including any tip), but enrich it with the
    RECEIPT's purchase date and itemized detail. reconciled=True marks it merged.
    """
    return statement.model_copy(
        update={
            "txn_date": receipt.txn_date,  # the real purchase date (pre-lag)
            "notes": receipt.notes or statement.notes,  # keep itemized detail
            "category": statement.category or receipt.category,
            "bonus_category": statement.bonus_category or receipt.bonus_category,
            "reconciled": True,
            # A merged record is only as safe as both inputs were.
            "pii_redacted": receipt.pii_redacted and statement.pii_redacted,
        }
    )


def reconcile(transactions: list[Transaction]) -> list[Transaction]:
    """Deduplicate a mixed list of receipts + statement lines.

    Each statement line is matched against at most one still-unmatched receipt.
    Matched pairs collapse to one reconciled record; everything else (unmatched
    statements, unmatched receipts, and MANUAL entries) passes through untouched.
    Input order of the surviving records is preserved as much as possible.
    """
    receipts = [t for t in transactions if t.source == TransactionSource.RECEIPT]
    used_receipt_ids: set[str] = set()
    result: list[Transaction] = []

    for txn in transactions:
        if txn.source == TransactionSource.STATEMENT:
            match = next(
                (
                    r
                    for r in receipts
                    if r.id not in used_receipt_ids and same_purchase(r, txn)
                ),
                None,
            )
            if match is not None:
                used_receipt_ids.add(match.id)
                result.append(_merge(match, txn))
            else:
                result.append(txn)
        elif txn.source == TransactionSource.RECEIPT:
            # Emit the receipt only if it did not get merged into a statement.
            # (Deferred: we append unmatched receipts in a second pass below.)
            continue
        else:  # MANUAL and anything else: pass through
            result.append(txn)

    # Append receipts that never matched a statement, preserving their order.
    for r in receipts:
        if r.id not in used_receipt_ids:
            result.append(r)

    return result
