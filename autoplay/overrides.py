"""Per-deck overrides file (YAML).

    key_cards: [Thassa's Oracle, Demonic Consultation]
    commander: [Kenrith, the Returned King]      # if the decklist doesn't mark it
    cards:
      Blood Artist: {add: [drain:1]}
      Rhystic Study: {set: [draw:1, card_draw]}   # replace auto tags
      Fellwar Stone: {colors: WUBRG}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .cards import Card


@dataclass
class Overrides:
    key_cards: set[str] = field(default_factory=set)
    commander: list[str] = field(default_factory=list)
    cards: dict[str, dict] = field(default_factory=dict)


def parse_tag(tag: str) -> tuple[str, int]:
    name, _, value = str(tag).partition(":")
    return name.strip(), int(value) if value else 1


def load_overrides(path: str | Path | None) -> Overrides:
    if not path:
        return Overrides()
    data = yaml.safe_load(Path(path).read_text()) or {}
    return Overrides(
        key_cards={n.lower() for n in data.get("key_cards", [])},
        commander=list(data.get("commander", [])),
        cards={k.lower(): v or {} for k, v in (data.get("cards") or {}).items()},
    )


def apply_overrides(card: Card, ov: Overrides) -> Card:
    name = card.name.lower()
    front = name.split(" // ")[0]
    card.key = name in ov.key_cards or front in ov.key_cards
    spec = ov.cards.get(name) or ov.cards.get(front)
    if not spec:
        return card
    if "set" in spec:
        card.tags = dict(parse_tag(t) for t in spec["set"])
    for t in spec.get("add", []):
        k, v = parse_tag(t)
        card.tags[k] = v
    for t in spec.get("remove", []):
        card.tags.pop(parse_tag(t)[0], None)
    if "colors" in spec:
        card.mana_colors = frozenset(str(spec["colors"]).upper())
    if "search" in spec:
        card.search_types = frozenset(spec["search"] if isinstance(spec["search"], list) else [spec["search"]])
    return card
