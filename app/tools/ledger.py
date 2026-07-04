"""The local redacted ledger — read/write with a structural PII guard.

DESIGN: the ledger is a plain JSON file on the user's machine (local-first — only
redacted, aggregated data ever leaves the sandbox). Persistence is the last line
of the ingestion trust boundary, so `save_ledger` REFUSES to write any record that
is not redacted. This turns "no full account/card number in the ledger" from a
hope into an enforced invariant: even a bug upstream cannot leak PII to disk,
because the write itself raises.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Transaction
from app.tools.redaction import contains_unredacted_pii

# The ledger is user data, not source — it is gitignored (see .gitignore).
DEFAULT_LEDGER_PATH = Path("app/data/ledger.json")


class UnredactedPersistError(RuntimeError):
    """Raised when something tries to persist a record still containing PII."""


def _assert_safe_to_persist(txn: Transaction) -> None:
    """The persistence guard: a record must be redacted and PII-free."""
    if not txn.pii_redacted:
        raise UnredactedPersistError(
            f"Refusing to persist transaction {txn.id!r}: pii_redacted is False."
        )
    if contains_unredacted_pii(txn.merchant) or contains_unredacted_pii(
        txn.notes or ""
    ):
        raise UnredactedPersistError(
            f"Refusing to persist transaction {txn.id!r}: unredacted PII detected."
        )


def load_ledger(path: Path = DEFAULT_LEDGER_PATH) -> list[Transaction]:
    """Load the ledger from disk, returning [] if it does not exist yet."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Transaction.model_validate(item) for item in raw]


def save_ledger(
    transactions: list[Transaction], path: Path = DEFAULT_LEDGER_PATH
) -> None:
    """Persist the full ledger, refusing any unredacted record (security guard)."""
    for txn in transactions:
        _assert_safe_to_persist(txn)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [t.model_dump(mode="json") for t in transactions]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_transactions(
    new_transactions: list[Transaction], path: Path = DEFAULT_LEDGER_PATH
) -> list[Transaction]:
    """Append records to the ledger and return the full updated ledger.

    Every new record passes the PII guard via save_ledger; existing records were
    already guarded when first written.
    """
    ledger = load_ledger(path)
    ledger.extend(new_transactions)
    save_ledger(ledger, path)
    return ledger
