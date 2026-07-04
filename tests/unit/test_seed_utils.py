"""Unit tests for seed-date rebasing (app/tools/seed_utils.py).

Pins the fix for the "budget warning only fires because of stale June data"
finding: every seeded row must land within the current calendar month, in the
original relative order, regardless of what day-of-month "today" is.
"""

from __future__ import annotations

import csv
import datetime
import io

from app.tools.seed_utils import rebase_csv_dates_to_current_month

_SAMPLE = (
    "date,merchant,amount\n"
    "2026-06-02,UNITED AIRLINES,512.00\n"
    "2026-06-15,CHIPOTLE,14.20\n"
    "2026-06-30,DELTA AIR LINES,62.00\n"
)


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_all_rows_land_within_the_current_month() -> None:
    today = datetime.date(2026, 7, 20)
    rebased = rebase_csv_dates_to_current_month(_SAMPLE, today=today)
    for row in _rows(rebased):
        d = datetime.date.fromisoformat(row["date"])
        assert d.year == 2026 and d.month == 7
        assert 1 <= d.day <= 20  # never later than "today"


def test_preserves_relative_order() -> None:
    """The row that was earliest originally must still be earliest after rebasing."""
    today = datetime.date(2026, 7, 20)
    rebased = _rows(rebase_csv_dates_to_current_month(_SAMPLE, today=today))
    dates = [datetime.date.fromisoformat(r["date"]) for r in rebased]
    merchants = [r["merchant"] for r in rebased]
    assert dates == sorted(dates)
    assert merchants == ["UNITED AIRLINES", "CHIPOTLE", "DELTA AIR LINES"]


def test_last_row_lands_on_today() -> None:
    today = datetime.date(2026, 7, 20)
    rebased = _rows(rebase_csv_dates_to_current_month(_SAMPLE, today=today))
    assert datetime.date.fromisoformat(rebased[-1]["date"]) == today


def test_works_early_in_the_month_by_compressing_the_spread() -> None:
    """If 'today' is only the 3rd, all rows must still fit in days 1-3."""
    today = datetime.date(2026, 7, 3)
    rebased = rebase_csv_dates_to_current_month(_SAMPLE, today=today)
    for row in _rows(rebased):
        d = datetime.date.fromisoformat(row["date"])
        assert d.year == 2026 and d.month == 7 and d.day <= 3


def test_amounts_and_row_count_are_untouched() -> None:
    today = datetime.date(2026, 7, 20)
    original = _rows(_SAMPLE)
    rebased = _rows(rebase_csv_dates_to_current_month(_SAMPLE, today=today))
    assert len(rebased) == len(original)
    assert {r["amount"] for r in rebased} == {r["amount"] for r in original}
