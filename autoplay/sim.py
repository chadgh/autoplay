"""Run many games and aggregate. This is the library entry point (CLI and a future
web app both call `simulate`)."""

from __future__ import annotations

import random
from dataclasses import replace

from .deck import Deck
from .game import Game, GameConfig
from .pilot import GreedyPilot
from .shuffle import Step, parse_routine
from .stats import aggregate


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


def simulate(
    deck: Deck,
    n: int = 1000,
    turns: int = 10,
    shuffle: str = "mash x3, riffle x2, cut",
    seed: int | None = None,
    baseline: bool = True,
    **config_overrides,
) -> dict:
    config = GameConfig(turns=turns, shuffle=parse_routine(shuffle), **config_overrides)
    result = {
        "deck": {
            "name": deck.name,
            "commanders": [c.name for c in deck.commanders],
            "size": len(deck.library) + len(deck.commanders),
            "lands": sum(c.is_land for c in deck.library),
            "key_cards": deck.key_cards(),
            "untagged": deck.untagged(),
            "off_identity": deck.off_identity(),
        },
        "settings": {"games": n, "turns": turns, "shuffle": shuffle, "seed": seed},
        "human": run_games(deck, n, config, seed),
    }
    if baseline:
        random_config = replace(config, shuffle=[Step("random")], search_shuffle=[Step("random")])
        result["random"] = run_games(deck, n, random_config, seed)
    return result
