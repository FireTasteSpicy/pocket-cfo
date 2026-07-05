---
name: card-benefits
description: >-
  Use to look up a credit card's exact terms — sign-up-bonus minimum-spend target,
  bonus deadline, and category reward multipliers (travel/dining/groceries/default).
  Trigger phrases: "what's the Amex multiplier?", "when is my bonus deadline?",
  "which card earns most on dining?". This is a REFERENCE skill: always read the
  numbers from resources/cards.yaml — never guess or invent card terms.
metadata:
  version: 1.0.0
  author: Pocket CFO
  license: Apache-2.0
---

# Card Benefits (reference)

The exact, static terms for every card the user holds live in
[`resources/cards.yaml`](resources/cards.yaml). This is a **reference skill**: its
whole purpose is to keep hard numbers (minimum-spend targets, deadlines,
multipliers) out of the prompt and out of the model's imagination. When you need a
card's terms, read them from the YAML — do not recall them from memory.

## What's in cards.yaml

Per card: `id`, `name`, `min_spend_target_cents` (or `null` if no active bonus),
`bonus_deadline` (ISO date or `null`), and `category_multipliers` keyed by bonus
category (`TRAVEL`, `DINING`, `GROCERIES`, `DEFAULT`).

## How it's consumed

`app/tools/cards.py` loads this file into validated `Card` objects. The
`which_card` tool on the Orchestrator combines these static terms with live
progress computed from the ledger to answer "which card should I use?". Because the numbers are read (not
generated), the recommendation is auditable: every figure in the rationale traces
back to a line in this file or to the ledger.

To add or edit a card, change `cards.yaml` only — no code change is needed.
