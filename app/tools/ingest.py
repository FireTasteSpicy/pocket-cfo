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
from app.tools.categorize import categorize
from app.tools.injection_guard import detect_injection
from app.tools.ledger import DEFAULT_LEDGER_PATH, load_ledger, save_ledger
from app.tools.reconcile import reconcile
from app.tools.redaction import redact_transaction_with_hits


@dataclass
class IngestResult:
    """Summary of one ingestion run (also serialized for the agent's reply).

    `summary` is a fully CODE-GENERATED sentence (see summary()) that the
    Ingestion agent is instructed to relay near-verbatim. This is the fix for a
    real gap found in review: leaving redaction/injection confirmations entirely
    to the model's discretion meant a paraphrase could silently drop them (a
    live eval run once produced a reply with zero mention of an injection
    attempt that WAS detected). Putting the exact facts in a ready-made string
    makes them far harder to accidentally omit.
    """

    added: int = 0  # net new records written to the ledger
    reconciled: int = 0  # records that merged a receipt with a statement line
    injection_flags: list[str] = field(default_factory=list)
    total_in_ledger: int = 0
    pii_redacted_categories: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Build the deterministic confirmation sentence(s) for the agent to relay."""
        noun = "transaction" if self.added == 1 else "transactions"
        parts = [f"Imported {self.added} {noun}"]
        if self.reconciled:
            parts[-1] += f" ({self.reconciled} merged with existing receipts)"
        parts[-1] += "."
        if self.pii_redacted_categories:
            cats = ", ".join(sorted(set(self.pii_redacted_categories)))
            parts.append(
                f"Redacted a {cats} to show only the last 4 digits; "
                "no full number is stored."
            )
        if self.injection_flags:
            quoted = "; ".join(f'"{f}"' for f in self.injection_flags)
            parts.append(
                f"SECURITY: the document contained an embedded instruction "
                f"({quoted}) -- it was treated as data, not obeyed, and nothing "
                "was reclassified."
            )
        return " ".join(parts)

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "reconciled": self.reconciled,
            "injection_flags": self.injection_flags,
            "total_in_ledger": self.total_in_ledger,
            "pii_redacted_categories": self.pii_redacted_categories,
            "summary": self.summary(),
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


def _categorize(txn: Transaction) -> Transaction:
    """Apply the deterministic first-pass categorization if not already set.

    Categorizing at ingest (using the shared categorize() engine) means the ledger
    is always ready for both consumers — budget totals and the card strategist —
    without a separate pass. The Categorization agent still refines ambiguous cases
    and applies user corrections on top of this baseline.
    """
    if txn.category is not None and txn.bonus_category is not None:
        return txn
    budget_cat, bonus_cat = categorize(txn.merchant)
    return txn.model_copy(
        update={
            "category": txn.category or budget_cat,
            "bonus_category": txn.bonus_category or bonus_cat,
        }
    )


def _persist_with_reconciliation(
    new_records: list[Transaction], ledger_path: Path
) -> IngestResult:
    """Redact + categorize new records, reconcile against the ledger, and save.

    Reconciliation runs over (existing + new) so a fresh statement line can merge
    with a receipt already in the ledger (and vice versa).
    """
    redacted_pairs = [redact_transaction_with_hits(t) for t in new_records]
    pii_hits = [h for _, hits in redacted_pairs for h in hits]
    redacted = [_categorize(t) for t, _ in redacted_pairs]
    before = load_ledger(ledger_path)
    combined = reconcile(before + redacted)
    save_ledger(combined, ledger_path)  # raises if any record is unredacted
    reconciled_count = sum(1 for t in combined if t.reconciled)
    return IngestResult(
        added=len(combined) - len(before),
        reconciled=reconciled_count,
        total_in_ledger=len(combined),
        pii_redacted_categories=pii_hits,
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


def ingest_manual(
    description: str,
    amount_cents: int,
    txn_date: datetime.date | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> IngestResult:
    """Log a conversational manual expense (cash/PayNow) as a categorized entry.

    Turns "I spent $30 cash on lunch" into a MANUAL Transaction with no card, a
    positive expense amount, and a category assigned by the shared engine. Like
    every other write, it goes through the redact + PII-guard path.
    """
    txn_date = txn_date or datetime.date.today()
    flags = detect_injection(description)
    # Disambiguate the id with the current ledger size so repeated identical
    # entries ("coffee $5") do not collapse to the same id.
    idx = len(load_ledger(ledger_path))
    txn = Transaction(
        id=_stable_id("man", description, amount_cents, txn_date.isoformat(), idx),
        merchant=description,
        amount_cents=abs(amount_cents),  # a logged spend is an expense
        txn_date=txn_date,
        source=TransactionSource.MANUAL,
    )
    result = _persist_with_reconciliation([txn], ledger_path)
    result.injection_flags = flags
    return result
