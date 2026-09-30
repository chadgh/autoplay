"""Load a decklist into tagged Card objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .cards import CACHE_PATH, Card, DeckEntry, card_from_scryfall, fetch_card_data, fetch_printings, parse_decklist
from .overrides import Overrides, apply_overrides
from .tagger import is_untagged, tag_card
from .tagger_api import cached_tags


@dataclass
class Deck:
    name: str
    commanders: list[Card]
    library: list[Card]  # the 99 (or so), in decklist order
    identity: frozenset = frozenset()
    scryfall_tags: dict[str, dict] = field(default_factory=dict)  # name -> Tagger {"tags", "relationships"}

    def untagged(self) -> list[str]:
        return sorted({c.name for c in self.library + self.commanders if is_untagged(c)})

    def off_identity(self) -> list[str]:
        """Cards outside the commander's color identity (illegal, and likely uncastable)."""
        return sorted({c.name for c in self.library if not c.color_identity <= self.identity})

    def key_cards(self) -> list[str]:
        return sorted({c.name for c in self.library if c.key})


def build_deck(name: str, entries, card_data: dict[str, dict], ov: Overrides, printings: dict | None = None) -> Deck:
    """`printings` maps (set, collector number) to Scryfall json for printings named in the
    decklist; they only change a card's image and link, never its game data."""
    printings = printings or {}
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
        printing = printings.get(e.printing)
        if printing and printing["name"] == base.name:  # a mistyped number could be another card
            shown = card_from_scryfall(printing)
            base.image_uri = shown.image_uri or base.image_uri
            base.scryfall_uri = shown.scryfall_uri or base.scryfall_uri
        for _ in range(e.count):
            card = apply_overrides(base.copy(), ov)
            if e.name.lower() in commander_names:
                card.is_commander = True
                commanders.append(card)
            else:
                library.append(card)
    return Deck(name, commanders, library, identity)


def deck_card_data(path: str | Path, ov: Overrides, cache_path: Path = CACHE_PATH, fetch=None):
    """Parse a decklist and return (entries, {lowercased name: scryfall json})."""
    entries = parse_decklist(Path(path).read_text())
    names = [e.name for e in entries] + ov.commander
    kwargs = {"fetch": fetch} if fetch else {}
    return entries, fetch_card_data(names, cache_path, **kwargs)


def load_deck(path: str | Path, ov: Overrides, cache_path: Path = CACHE_PATH, fetch=None) -> Deck:
    entries, data = deck_card_data(path, ov, cache_path, fetch)
    printings = fetch_printings([e.printing for e in entries if e.printing], cache_path.parent / "printings.json")
    deck = build_deck(Path(path).stem, entries, data, ov, printings)
    deck.scryfall_tags = cached_tags(data, cache_path.parent / "tags.json")
    return deck
