"""Load a decklist into tagged Card objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cards import CACHE_PATH, Card, DeckEntry, card_from_scryfall, fetch_card_data, parse_decklist
from .overrides import Overrides, apply_overrides
from .tagger import is_untagged, tag_card


@dataclass
class Deck:
    name: str
    commanders: list[Card]
    library: list[Card]  # the 99 (or so), in decklist order
    identity: frozenset = frozenset()

    def untagged(self) -> list[str]:
        return sorted({c.name for c in self.library + self.commanders if is_untagged(c)})

    def key_cards(self) -> list[str]:
        return sorted({c.name for c in self.library if c.key})


def build_deck(name: str, entries, card_data: dict[str, dict], ov: Overrides) -> Deck:
    commander_names = {n.lower() for n in ov.commander} | {e.name.lower() for e in entries if e.commander}
    if not commander_names:
        raise ValueError("no commander found: mark it in the decklist or set `commander:` in overrides")
    identity = frozenset(
        c for n in commander_names for c in card_data[n].get("color_identity", [])
    )
    listed = {e.name.lower() for e in entries}
    entries = [DeckEntry(n, 1, True) for n in ov.commander if n.lower() not in listed] + list(entries)
    commanders: list[Card] = []
    library: list[Card] = []
    for e in entries:
        base = tag_card(card_from_scryfall(card_data[e.name.lower()]), identity)
        for _ in range(e.count):
            card = apply_overrides(base.copy(), ov)
            if e.name.lower() in commander_names:
                card.is_commander = True
                commanders.append(card)
            else:
                library.append(card)
    return Deck(name, commanders, library, identity)


def load_deck(path: str | Path, ov: Overrides, cache_path: Path = CACHE_PATH, fetch=None) -> Deck:
    path = Path(path)
    entries = parse_decklist(path.read_text())
    names = [e.name for e in entries] + ov.commander
    kwargs = {"fetch": fetch} if fetch else {}
    data = fetch_card_data(names, cache_path, **kwargs)
    return build_deck(path.stem, entries, data, ov)
