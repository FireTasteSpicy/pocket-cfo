---
name: statement-reconciler
description: >-
  Use when reconciling or deduplicating financial transactions — deciding whether
  a receipt and a bank-statement line describe the SAME purchase despite
  settlement-date lag and a tip, and collapsing them into one enriched record.
  Trigger phrases: "reconcile my statement", "did this receipt already post?",
  "why is this charge listed twice?". Do NOT use this for categorizing spending or
  for recommending which card to use — those are other skills.
metadata:
  version: 1.0.0
  author: Pocket CFO
  license: Apache-2.0
  requires:
    bins: [python3]
---

# Statement Reconciler

A receipt and its bank-statement line rarely match cleanly: the statement posts a
day or two later (settlement lag), and if you tipped, the amounts differ. This
skill decides when two records are the **same purchase** and merges them, so the
budget and card-bonus totals are never double-counted.

## The matching policy (deterministic — do not eyeball it)

Two records are the same purchase when **all three** hold:

1. **Merchant match** — after normalizing case, punctuation, and store numbers
   (`TRADER JOE'S #123` → `TRADER JOES`), the smaller token set is contained in
   the larger. This links `Trader Joe's` ↔ `TRADER JOE'S #123`.
2. **Amount within a tip** — the statement amount is the receipt amount, plus at
   most ~25% (a tip). A wildly different amount (e.g. $47.83 vs $88.10) is a
   *different* purchase and must NOT be merged.
3. **Settlement lag** — the statement posted within ~5 days of the receipt date.

When merged, keep the statement's authoritative charged amount, posted date, and
card, but enrich it with the receipt's purchase date and itemized detail.

## How to run it

The policy above is implemented as tested code in `app/tools/reconcile.py`. This
skill's script is a thin CLI over it (single source of truth — the logic is unit
tested in `tests/unit/test_reconcile.py`):

```bash
python3 .agents/skills/statement-reconciler/scripts/reconcile.py transactions.json
# prints the deduplicated ledger as JSON; merged records have "reconciled": true
```

Prefer calling `app.tools.reconcile.reconcile(transactions)` directly from agent
code; use the script when reconciling a standalone JSON file.
