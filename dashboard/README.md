# Dashboard

A glassmorphic progress-bar view of Pocket CFO — the best visual clip for the
demo video. Every number is computed from the **real redacted ledger** by the same
deterministic tools the agents use (`generate.py` ingests the seed statement and
calls `card_strategy` / `aggregate`), so nothing here is mocked.

```bash
uv run python dashboard/generate.py    # writes dashboard/index.html
# then open dashboard/index.html in a browser
```

It shows three things:
1. **The hero recommendation** — "which card for a $500 flight?" answered in one sentence.
2. **Sign-up-bonus progress** — a filling bar per card ($2,500 of $3,000 on the Amex, days left).
3. **This month's budget** — a bar per category, with over-budget categories flagged in amber.

`generate.py` uses a fixed `REFERENCE_DATE` (2026-07-05) so the committed
`index.html` is coherent (the Amex bonus reads "8 days left"). Regenerate on the
day you record so "days left" reflects the demo date.
