#!/usr/bin/env python3
"""statement-reconciler skill script — deduplicate a transactions JSON file.

This is a thin CLI over the tested logic in app/tools/reconcile.py (single source
of truth). It exists so the skill can run as a standalone script on a JSON file,
per the course's "script skill" pattern — deterministic work runs as code, not as
model guesswork, and never enters the model's token window.

Usage:
    python3 reconcile.py transactions.json      # -> reconciled JSON on stdout

Input: a JSON array of Transaction objects (see app/models/schemas.py).
Output: the deduplicated array; merged records have "reconciled": true.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable so we reuse the tested reconciliation logic
# rather than duplicating it here (skills live outside the `app` package tree).
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from app.models import Transaction  # noqa: E402
from app.tools.reconcile import reconcile  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    txns = [Transaction.model_validate(item) for item in raw]
    merged = reconcile(txns)
    print(json.dumps([t.model_dump(mode="json") for t in merged], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
