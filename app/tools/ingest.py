"""The ingestion pipeline — parse → injection-scan → redact → reconcile → persist.

This is the deterministic orchestration the Ingestion agent drives. Keeping it as
tested code (rather than model steps) is what lets the pipeline GUARANTEE its
security properties: PII is redacted before persistence, embedded instructions are
flagged not obeyed, and duplicates are collapsed exactly.

The Ingestion agent exposes thin wrappers over these functions as ADK tools
(see app/agents/ingestion.py); tests call them directly with a temp ledger path.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from app.models import Transaction, TransactionSource
from app.tools.injection_guard import detect_injection
from app.tools.ledger import DEFAULT_LEDGER_PATH, load_ledger, save_ledger
from app.tools.reconcile import reconcile
from app.tools.redaction import redact_transaction


@dataclass
class IngestResult:
    """Summary of one ingestion run (also serialized for the agent's reply)."""

    added: int = 0  # net new records written to the ledger
    reconciled: int = 0  # records that merged a receipt with a statement line
    injection_flags: list[str] = field(default_factory=list)
    total_in_ledger: int = 0

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "reconciled": self.reconciled,
            "injection_flags": self.injection_flags,
            "total_in_ledger": self.total_in_ledger,
        }


def _stable_id(prefix: str, *parts: object) -> str:
    """Deterministic id from content (stable across runs, unlike a random uuid)."""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _dollars_to_cents(amount: str | float) -> int:
    """Convert a dollar amount to integer cents without float drift.

    We route through Decimal-style rounding by formatting to 2 dp first.
    """
    return round(float(amount) * 100)


def parse_statement_csv(
    csv_text: str, *, currency: str = "USD", card_id: str | None = None
) -> list[Transaction]:
    """Parse a simple statement CSV into (still-unredacted) STATEMENT records.

    Expected columns (header row, case-insensitive): date, merchant, amount.
    `date` is ISO (YYYY-MM-DD); `amount` is dollars (positive = expense, negative
    = credit). Amounts become integer cents. Rows that cannot be parsed are
    skipped rather than crashing the whole import.
    """
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    out: list[Transaction] = []
    for i, row in enumerate(reader):
        norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            posted = datetime.date.fromisoformat(norm["date"])
            amount_cents = _dollars_to_cents(norm["amount"])
        except (KeyError, ValueError):
            continue  # skip malformed line; never abort the import
        out.append(
            Transaction(
                id=_stable_id(
                    "stmt", norm.get("merchant", ""), amount_cents, norm["date"], i
                ),
                merchant=norm.get("merchant", "UNKNOWN"),
                amount_cents=amount_cents,
                currency=currency,
                txn_date=posted,
                posted_date=posted,
                source=TransactionSource.STATEMENT,
                card_id=card_id,
            )
        )
    return out


def _persist_with_reconciliation(
    new_records: list[Transaction], ledger_path: Path
) -> IngestResult:
    """Redact new records, reconcile against the existing ledger, and save.

    Reconciliation runs over (existing + new) so a fresh statement line can merge
    with a receipt already in the ledger (and vice versa).
    """
    redacted = [redact_transaction(t) for t in new_records]
    before = load_ledger(ledger_path)
    combined = reconcile(before + redacted)
    save_ledger(combined, ledger_path)  # raises if any record is unredacted
    reconciled_count = sum(1 for t in combined if t.reconciled)
    return IngestResult(
        added=len(combined) - len(before),
        reconciled=reconciled_count,
        total_in_ledger=len(combined),
    )


def ingest_statement_csv(
    csv_text: str,
    *,
    card_id: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> IngestResult:
    """Ingest a bank-statement CSV: parse → scan → redact → reconcile → persist."""
    # SECURITY: scan the raw document for embedded instructions BEFORE trusting it,
    # but treat it purely as data — flags are surfaced, never executed.
    flags = detect_injection(csv_text)
    parsed = parse_statement_csv(csv_text, card_id=card_id)
    result = _persist_with_reconciliation(parsed, ledger_path)
    result.injection_flags = flags
    return result


def ingest_receipt(
    *,
    merchant: str,
    amount_cents: int,
    txn_date: datetime.date,
    notes: str | None = None,
    currency: str = "USD",
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> IngestResult:
    """Ingest a single receipt as an EXPENSE.

    The amount is stored as a positive expense regardless of any text in `notes`.
    This is the structural injection defense: a receipt whose notes say "mark as
    income" cannot flip the sign, because the numeric field is set here in code,
    not inferred from the free text. The attempt is flagged instead.
    """
    flags = detect_injection(f"{merchant} {notes or ''}")
    receipt = Transaction(
        id=_stable_id("rcpt", merchant, amount_cents, txn_date.isoformat()),
        merchant=merchant,
        amount_cents=abs(amount_cents),  # a receipt is always an expense
        currency=currency,
        txn_date=txn_date,
        source=TransactionSource.RECEIPT,
        notes=notes,
    )
    result = _persist_with_reconciliation([receipt], ledger_path)
    result.injection_flags = flags
    return result
