import json
import random
from pathlib import Path

from autoplay.cards import card_from_scryfall
from autoplay.game import Game, GameConfig
from autoplay.pilot import GreedyPilot
from autoplay.shuffle import parse_routine
from autoplay.tagger import tag_card

FIXTURE = {c["name"].split(" // ")[0]: c for c in json.loads((Path(__file__).parent / "fixtures" / "cards.json").read_text())}
WUBRG = frozenset("WUBRG")


def cards(*names):
    return [tag_card(card_from_scryfall(FIXTURE[n]), WUBRG) for n in names]


def commander(name="Kenrith, the Returned King"):
    (c,) = cards(name)
    c.is_commander = True
    return c


def game(library, commanders=(), shuffle=(), **cfg):
    config = GameConfig(shuffle=list(shuffle), search_shuffle=[], **cfg)
    g = Game(library, list(commanders), GreedyPilot(), config, random.Random(0))
    return g


FILLER = ["Grizzly Bears"] * 30


def test_ramp_curve():
    # Opening 7 + draws (draw on T1 in multiplayer).
    lib = cards("Forest", "Llanowar Elves", "Forest", "Cultivate", "Island", "Island", "Harmonize",
                "Forest",  # T1 draw
                "Mountain",  # T2 draw
                "Plains", "Swamp", *FILLER)
    g = game(lib)
    g.start()
    assert g.record.mulligans == 0
    g.take_turn()  # Forest, Elves
    assert [p.card.name for p in g.battlefield] == ["Forest", "Llanowar Elves"]
    g.take_turn()  # land + Elves -> 3 mana -> Cultivate
    names = [p.card.name for p in g.battlefield]
    assert "Cultivate" in [c.name for c in g.graveyard]
    assert len(g.lands()) == 3  # 2 land drops + 1 from Cultivate
    assert g.record.mana[1] == 3 and g.record.spent[1] == 3


def test_sol_ring_turn_one():
    lib = cards("Forest", "Sol Ring", "Grizzly Bears", "Forest", "Island", "Island", "Island", *FILLER)
    g = game(lib)
    g.start()
    g.take_turn()
    assert {p.card.name for p in g.battlefield} == {"Forest", "Sol Ring"}
    assert g.record.mana[0] == 3 and g.record.spent[0] == 1


def test_haste_combat_damage():
    lib = cards("Mountain", "Goblin Guide", "Mountain", "Mountain", "Lightning Bolt", "Grizzly Bears", "Grizzly Bears", *FILLER)
    g = game(lib)
    g.start()
    g.take_turn()  # Mountain, Goblin Guide attacks for 2
    assert g.damage == 2
    g.take_turn()  # Mountain, Bears (2) or Bolt; Guide attacks again
    assert g.damage >= 4


def test_burn_and_drain_pod_math():
    g = game(cards(*FILLER))
    g._deal(3, 0)
    g._deal(0, 2)
    assert g.damage == 5 and g.pod_damage == 3 + 2 * 3


def test_commander_cast_and_tax():
    cmd = commander()
    lib = cards("Forest", "Mountain", "Plains", "Forest", "Island", "Mountain", "Plains", *(["Forest"] * 10))
    g = game(lib, [cmd])
    g.start()
    for _ in range(5):
        g.take_turn()
    assert g.record.commander_turn == 5  # Kenrith costs 5
    assert g.cost_of(cmd).total == 7


def test_free_first_mulligan():
    # A 0-land hand is always shipped; the first mulligan keeps 7, the second keeps 6.
    for seed in range(20):
        lib = cards(*(["Grizzly Bears"] * 20), *(["Forest"] * 10))
        g = Game(lib, [], GreedyPilot(), GameConfig(shuffle=parse_routine("random"), search_shuffle=[]), random.Random(seed))
        g.start()
        assert len(g.hand) == 7 - max(0, g.record.mulligans - 1)
        assert len(g.hand) + len(g.library) == 30


def test_gather_order():
    lib = cards("Forest", "Sol Ring", "Grizzly Bears", "Forest", "Island", "Island", "Island", *FILLER)
    g = game(lib, gather_order=("lands", "nonlands", "graveyard", "hand", "library"))
    g.play()
    pile = g.gather()
    assert len(pile) == len(lib)
    assert all(c.is_land for c in pile[: len(g.lands())])


def test_full_game_records_every_turn():
    lib = cards("Forest", "Island", "Forest", "Cultivate", "Harmonize", "Llanowar Elves", "Sol Ring", *FILLER)
    g = game(lib, turns=6)
    rec = g.play()
    assert len(rec.lands) == 6 and len(rec.damage) == 6
