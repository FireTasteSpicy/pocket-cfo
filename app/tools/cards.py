"""Load card terms from the card-benefits reference skill.

Single source of truth: the numbers live in
`.agents/skills/card-benefits/resources/cards.yaml` (a reference skill). This
module validates that YAML into `Card` objects so the rest of the system works
with typed data, and so a malformed card file fails loudly at load time rather
than mid-recommendation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.models import Card

# The reference skill's resource file (read, never written by the agent).
CARDS_YAML_PATH = Path(".agents/skills/card-benefits/resources/cards.yaml")


def load_cards(path: Path = CARDS_YAML_PATH) -> list[Card]:
    """Load and validate all cards from the reference YAML."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Card.model_validate(entry) for entry in data.get("cards", [])]


def get_card(cards: list[Card], card_id: str) -> Card | None:
    """Find a card by id, or None."""
    return next((c for c in cards if c.id == card_id), None)
