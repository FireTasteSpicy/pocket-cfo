#!/usr/bin/env python3
"""Generate the Pocket CFO dashboard (dashboard/index.html) from REAL computed data.

This is the video money-shot: filling minimum-spend progress bars and budget bars,
plus the hero "which card?" recommendation — all produced by the same deterministic
tools the agents use (no mock numbers). Run it, open the HTML, and every figure
traces back to the ledger + cards.yaml.

    uv run python dashboard/generate.py     # writes dashboard/index.html

Uses the REAL wall-clock date, not a hardcoded one: the seed statement's dates are
rebased onto the current calendar month at generation time (see
app/tools/seed_utils.py) so the budget-vs-actual numbers are always real current-
month spend, and "days left" on the Amex bonus is always accurate. Regenerate right
before recording so the numbers reflect the demo day.
"""

from __future__ import annotations

import datetime
import html
import tempfile
from pathlib import Path

from app.tools.aggregate import (
    compute_budget_status,
    compute_card_progress,
    load_budgets,
)
from app.tools.card_strategy import recommend_card
from app.tools.cards import load_cards
from app.tools.categorize import categorize
from app.tools.ingest import ingest_statement_csv
from app.tools.ledger import load_ledger
from app.tools.seed_utils import rebase_csv_dates_to_current_month

OUT_PATH = Path("dashboard/index.html")
SEED_STATEMENT = Path("app/data/seed/sample_statement.csv")


def _build_data(today: datetime.date | None = None):
    """Ingest the seed statement (rebased to the current month) and compute
    cards, budgets, and the hero rec -- all as of `today` (real wall-clock date
    by default; tests can pass a fixed one)."""
    today = today or datetime.date.today()
    tmp_ledger = Path(tempfile.mkdtemp()) / "ledger.json"
    rebased_csv = rebase_csv_dates_to_current_month(
        SEED_STATEMENT.read_text(), today=today
    )
    ingest_statement_csv(rebased_csv, card_id="amex_gold", ledger_path=tmp_ledger)
    ledger = load_ledger(tmp_ledger)
    cards = compute_card_progress(load_cards(), ledger)
    budgets = compute_budget_status(
        load_budgets(), ledger, month=(today.year, today.month)
    )
    _, bonus = categorize("a $500 flight")
    rec = recommend_card(50_000, bonus, cards, budgets=budgets, today=today)
    return cards, budgets, rec, today


def _bar(pct: float, over: bool) -> str:
    """Render one progress bar (clamped to 100% width; amber when over limit)."""
    width = min(100.0, pct)
    cls = "fill over" if over else "fill"
    return (
        f'<div class="track"><div class="{cls}" style="width:{width:.1f}%"></div></div>'
    )


def _card_progress_html(cards, today: datetime.date) -> str:
    rows = []
    for c in cards:
        if c.min_spend_target_cents is None:
            continue
        spent = c.min_spend_progress_cents / 100
        target = c.min_spend_target_cents / 100
        remaining = c.min_spend_remaining_cents() / 100
        pct = (c.min_spend_progress_cents / c.min_spend_target_cents) * 100
        days = (c.bonus_deadline - today).days if c.bonus_deadline else None
        days_txt = f"{days} days left" if days is not None else ""
        rows.append(
            f"""
        <div class="row">
          <div class="row-head">
            <span class="name">{html.escape(c.name)}</span>
            <span class="muted">${spent:,.0f} / ${target:,.0f} &middot; {days_txt}</span>
          </div>
          {_bar(pct, over=False)}
          <div class="sub">${remaining:,.0f} to go to clear the sign-up bonus</div>
        </div>"""
        )
    return "\n".join(rows)


def _budget_html(budgets) -> str:
    rows = []
    for b in budgets:
        if b.spent_cents == 0:
            continue
        spent = b.spent_cents / 100
        limit = b.monthly_limit_cents / 100
        pct = (
            (b.spent_cents / b.monthly_limit_cents) * 100
            if b.monthly_limit_cents
            else 0
        )
        over = b.spent_cents > b.monthly_limit_cents
        tag = '<span class="pill">over budget</span>' if over else ""
        rows.append(
            f"""
        <div class="row">
          <div class="row-head">
            <span class="name">{html.escape(b.category)} {tag}</span>
            <span class="muted">${spent:,.2f} / ${limit:,.0f}</span>
          </div>
          {_bar(pct, over=over)}
        </div>"""
        )
    return "\n".join(rows)


def render(cards, budgets, rec, today: datetime.date) -> str:
    """Render the full self-contained glassmorphic dashboard HTML."""
    rationale = html.escape(rec.rationale)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Pocket CFO</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #f4f4f8; min-height: 100vh; padding: 40px 18px;
    background: radial-gradient(1200px 600px at 15% -10%, #4338ca 0%, transparent 55%),
                radial-gradient(1000px 700px at 110% 10%, #0ea5e9 0%, transparent 50%),
                linear-gradient(160deg, #0b1020 0%, #131a32 60%, #0b1020 100%);
    background-attachment: fixed;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  header {{ text-align: center; margin-bottom: 28px; }}
  header h1 {{ font-size: 34px; letter-spacing: -0.5px; }}
  header p {{ color: #b9c0e0; margin-top: 6px; font-size: 15px; }}
  .badge {{
    display: inline-block; margin-top: 12px; padding: 5px 14px; font-size: 12px;
    border-radius: 999px; background: rgba(255,255,255,.08);
    border: 1px solid rgba(255,255,255,.16); color: #cfe3ff;
  }}
  .glass {{
    background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.14);
    border-radius: 20px; padding: 22px 24px; margin-bottom: 20px;
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    box-shadow: 0 10px 40px rgba(0,0,0,.35);
  }}
  .glass h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
    color: #aab4e0; margin-bottom: 16px; font-weight: 600; }}
  .hero {{ background: linear-gradient(135deg, rgba(99,102,241,.30), rgba(14,165,233,.18)); }}
  .hero .q {{ color: #cfe3ff; font-size: 14px; margin-bottom: 8px; }}
  .hero .a {{ font-size: 21px; line-height: 1.45; font-weight: 600; }}
  .hero .a b {{ color: #a5f3d0; }}
  .row {{ margin-bottom: 18px; }}
  .row:last-child {{ margin-bottom: 4px; }}
  .row-head {{ display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 8px; font-size: 15px; }}
  .name {{ font-weight: 600; }}
  .muted {{ color: #aeb6d8; font-size: 13px; }}
  .sub {{ color: #98a0c4; font-size: 12px; margin-top: 6px; }}
  .track {{ height: 12px; border-radius: 999px; background: rgba(255,255,255,.10);
    overflow: hidden; }}
  .fill {{ height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, #34d399, #38bdf8); }}
  .fill.over {{ background: linear-gradient(90deg, #fbbf24, #f43f5e); }}
  .pill {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; vertical-align: middle;
    background: rgba(244,63,94,.22); border: 1px solid rgba(244,63,94,.5); color: #ffd3da; }}
  footer {{ text-align: center; color: #7f88ad; font-size: 12px; margin-top: 8px; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Pocket&nbsp;CFO</h1>
      <p>A privacy-first finance concierge that reasons about your money.</p>
      <span class="badge">read-only &middot; never moves money &middot; PII redacted locally</span>
    </header>

    <section class="glass hero">
      <div class="q">"I'm about to book a $500 flight &mdash; which card should I use?"</div>
      <div class="a">💳 <b>{html.escape(rec.card_name)}</b> &mdash; {rationale}</div>
    </section>

    <section class="glass">
      <h2>Sign-up bonus progress</h2>
      {_card_progress_html(cards, today)}
    </section>

    <section class="glass">
      <h2>This month's budget</h2>
      {_budget_html(budgets)}
    </section>

    <footer>Generated from the redacted ledger &middot; every figure traces to cards.yaml or the ledger.</footer>
  </div>
</body>
</html>
"""


def main() -> None:
    cards, budgets, rec, today = _build_data()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(cards, budgets, rec, today), encoding="utf-8")
    print(f"Wrote {OUT_PATH}  (hero: {rec.card_name} — {rec.deciding_factor.value})")


if __name__ == "__main__":
    main()
