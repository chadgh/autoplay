"""Run many games and aggregate. This is the library entry point (CLI and a future
web app both call `simulate`)."""

from __future__ import annotations

import random
from dataclasses import replace
from functools import partial

from .deck import Deck
from .game import Game, GameConfig
from .pilot import GreedyPilot, LandfallPilot
from .shuffle import Step, parse_routine
from .stats import aggregate

PILOTS = {"greedy": GreedyPilot, "landfall": LandfallPilot}


def run_games(deck: Deck, n: int, config: GameConfig, seed: int | None = None, pilot_factory=GreedyPilot) -> dict:
    """Play n games, each starting from the previous game's gathered-up deck order."""
    rng = random.Random(seed)
    order = list(deck.library)  # first game starts in decklist order
    records = []
    for _ in range(n):
        game = Game(order, deck.commanders, pilot_factory(), config, rng)
        records.append(game.play())
        order = game.gather()
    return aggregate(records, config.turns, deck.key_cards())


# Tagger tags about names, templating, and set design rather than what a card does.
TRIVIA_TAGS = {
    "triggered ability", "activated ability", "card names", "single english word name", "alliteration",
    "namesake spell", "eponymous", "interchangeable name", "quote name", "unique type line", "flavors of vanilla",
    "staple with set's mechanic", "mana rock with set's mechanic", "useless outside commander", "hybrid-mana",
    "intervening if clause", "delayed trigger", "virtual french vanilla", "virtual vanilla", "virtual legendary",
    "more expensive than mv", "oversized", "uril ability", "fetchable", "blue effect", "hate",
}


def _is_trivia(tag: str) -> bool:
    return tag in TRIVIA_TAGS or tag.startswith("cycle")


def scryfall_tags_summary(deck: Deck) -> dict:
    """Tagger tags per card, tags shared by 2+ cards, and relationships between cards in the deck."""
    names = list(dict.fromkeys(c.name for c in deck.commanders + deck.library))
    in_deck = set(names)
    cards = {n: [t for t in deck.scryfall_tags[n]["tags"] if not _is_trivia(t)] for n in names if n in deck.scryfall_tags}
    by_tag: dict[str, list[str]] = {}
    for name, tags in cards.items():
        for tag in tags:
            by_tag.setdefault(tag, []).append(name)
    relationships, seen = [], set()
    for info in deck.scryfall_tags.values():
        for r in info["relationships"]:
            ident = (r["kind"], r["a"], r["b"])
            if r["a"] != r["b"] and r["a"] in in_deck and r["b"] in in_deck and ident not in seen:
                seen.add(ident)
                relationships.append(r)
    return {
        "cards": cards,
        "shared": sorted(([t, ns] for t, ns in by_tag.items() if len(ns) > 1), key=lambda g: (-len(g[1]), g[0])),
        "relationships": relationships,
        "missing": [n for n in names if n not in cards],
    }


def simulate(
    deck: Deck,
    n: int = 1000,
    turns: int = 10,
    shuffle: str = "mash x3, riffle x2, cut",
    search_shuffle: str = "mash x2, cut",
    seed: int | None = None,
    baseline: bool = True,
    pilot: str = "greedy",
    keep_lands: tuple[int, int] = (2, 5),
    **config_overrides,
) -> dict:
    keep_min, keep_max = keep_lands
    if not 0 <= keep_min <= keep_max <= 7:
        raise ValueError(f"keep_lands must be 0 <= min <= max <= 7, got {keep_min}-{keep_max}")
    pilot_factory = partial(PILOTS[pilot], keep_min=keep_min, keep_max=keep_max)
    config = GameConfig(
        turns=turns, shuffle=parse_routine(shuffle), search_shuffle=parse_routine(search_shuffle), **config_overrides
    )
    result = {
        "deck": {
            "name": deck.name,
            "commanders": [c.name for c in deck.commanders],
            "identity": [c for c in "WUBRG" if c in deck.identity],
            "size": len(deck.library) + len(deck.commanders),
            "lands": sum(c.is_land for c in deck.library),
            "key_cards": deck.key_cards(),
            "untagged": deck.untagged(),
            "off_identity": deck.off_identity(),
            "scryfall_tags": scryfall_tags_summary(deck),
            "links": {c.name: c.scryfall_uri for c in deck.commanders + deck.library if c.scryfall_uri},
            "images": {c.name: c.image_uri for c in deck.commanders + deck.library if c.image_uri},
        },
        "settings": {"games": n, "turns": turns, "shuffle": shuffle, "search_shuffle": search_shuffle, "seed": seed, "pilot": pilot,
                     "keep_lands": [keep_min, keep_max]},
        "human": run_games(deck, n, config, seed, pilot_factory),
    }
    if baseline:
        random_config = replace(config, shuffle=[Step("random")], search_shuffle=[Step("random")])
        result["random"] = run_games(deck, n, random_config, seed, pilot_factory)
    return result
