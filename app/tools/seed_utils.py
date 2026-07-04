"""Seed-data date rebasing — keeps the demo's "current month" story honest.

WHY THIS EXISTS: `compute_budget_status` filters spend to the CURRENT calendar
month (that is what "monthly limit" means). The seed statement's dates are
hardcoded to June 2026, so a demo run in any other month would show $0 spent in
every category and the budget-guardrail branch (the hero's celebrated over-budget
warning) would never fire. This module rebases the seed CSV's dates onto the
CURRENT month at seed time — every demo run "looks like" the story happened this
month, however far the wall clock has moved, without editing the checked-in CSV
(which stays readable, git-diffable, and unit-test-stable).

This is a SEEDING-time concern only. `app/tools/ingest.py` and its unit tests are
untouched and continue to operate on whatever dates they're given.
"""

from __future__ import annotations

import csv
import datetime
import io


def rebase_csv_dates_to_current_month(
    csv_text: str, today: datetime.date | None = None
) -> str:
    """Remap every row's `date` into [first-of-this-month, today], in order.

    Preserves the original RELATIVE order and spacing (proportionally compressed
    if today is early in the month) so the narrative — travel-heavy early,
    groceries/dining threaded through, one accidental account-number line — still
    reads the same, it just always lands within the current calendar month.

    Args:
        csv_text: statement CSV with a header row and a `date` column (YYYY-MM-DD).
        today: reference date (defaults to the real today; tests pass one explicitly).

    Returns:
        The same CSV with every `date` rebased into the current month.
    """
    today = today or datetime.date.today()
    month_start = today.replace(day=1)
    available_days = (today - month_start).days  # 0 if today is the 1st

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    fieldnames = reader.fieldnames
    rows = sorted(reader, key=lambda r: r["date"])  # preserve chronological order
    n = len(rows)

    out_rows = []
    for i, row in enumerate(rows):
        offset = available_days if n <= 1 else round(i * available_days / (n - 1))
        new_date = month_start + datetime.timedelta(days=offset)
        row = dict(row)
        row["date"] = new_date.isoformat()
        out_rows.append(row)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)
    return buf.getvalue()
