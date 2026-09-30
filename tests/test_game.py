import json
import random
from pathlib import Path

from autoplay.cards import Card, card_from_scryfall
from autoplay.game import Game, GameConfig, Permanent
from autoplay.pilot import GreedyPilot, LandfallPilot
from autoplay.shuffle import parse_routine
from autoplay.stats import GameRecord
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


def test_landfall_draw():
    g = game(cards(*FILLER))
    (tatyova, forest) = cards("Tatyova, Benthic Druid", "Forest")
    g._resolve(tatyova)
    g._enter_land(forest, tapped=False)
    assert len(g.hand) == 1


def test_landfall_tag():
    (tatyova, bears) = cards("Tatyova, Benthic Druid", "Grizzly Bears")
    assert tatyova.tags.get("landfall") and not bears.tags.get("landfall")


def _landfall_board(pilot):
    g = Game(cards(*FILLER), [], pilot, GameConfig(shuffle=[], search_shuffle=[]), random.Random(0))
    for land in cards("Forest", "Forest", "Forest", "Island", "Island", "Island"):
        g._enter_land(land, tapped=False)
    g.hand = cards("Tatyova, Benthic Druid", "Forest")
    return g


def test_landfall_pilot_casts_trigger_before_land():
    g = _landfall_board(LandfallPilot())
    g.pilot.main_phase(g)
    assert len(g.lands()) == 7
    assert len(g.library) == len(FILLER) - 1  # Tatyova drew off the land drop


def test_greedy_pilot_plays_land_first():
    g = _landfall_board(GreedyPilot())
    g.pilot.main_phase(g)
    assert len(g.lands()) == 7
    assert len(g.library) == len(FILLER)


def test_tutor_to_top_respects_type():
    lib = cards("Island", "Mystical Tutor", "Island", "Island", "Island", "Island", "Island",
                *(["Grizzly Bears"] * 10), "Lightning Bolt", "Thassa's Oracle", *FILLER)
    for c in lib:
        c.key = c.name in ("Lightning Bolt", "Thassa's Oracle")
    g = game(lib)
    g.start()
    g.take_turn()  # Island, Mystical Tutor -> Bolt (instant) on top, not Oracle (creature)
    assert g.library[0].name == "Lightning Bolt"


def test_record_opening_hand_sorts_spells_then_lands():
    rec = GameRecord()
    rec.note_opening_hand([Card("Forest", type_line="Basic Land — Forest"), Card("Big", cmc=5, type_line="Creature"),
                           Card("Small", cmc=1, type_line="Instant", tags={"interaction": 1})])
    assert rec.opening_hand == ["Small", "Big", "Forest"]
    assert rec.opening_profile == {"cards": 3, "lands": 1, "ramp": 0, "card_draw": 0, "interaction": 1, "spell_mv": 3}


def test_tap_draw_on_attack():
    g = game(cards(*FILLER))
    (gran,) = cards("Gran-Gran")
    g.battlefield.append(Permanent(gran))
    g._combat()
    g._combat()  # already tapped: no second trigger
    assert len(g.library) == len(FILLER) - 1


def test_tap_draw_not_on_vigilance_attack():
    g = game(cards(*FILLER))
    (gran,) = cards("Gran-Gran")
    gran.keywords = frozenset({"Vigilance"})
    g.battlefield.append(Permanent(gran))
    g._combat()
    assert g.hand == []


def test_tap_draw_when_tapped_for_mana_but_not_entering_tapped():
    g = game(cards(*FILLER))
    (land,) = cards("Forest")
    land.tags["tap_draw"] = 1
    g._enter_land(land, tapped=True)
    assert g.hand == []
    g.take_turn()  # untaps, draws for turn, then taps the land for mana
    assert len(g.hand) == 2


def test_tap_draw_loots():
    g = game(cards(*FILLER))
    (gran,) = cards("Gran-Gran")
    g.battlefield.append(Permanent(gran))
    g._combat()
    assert g.hand == [] and [c.name for c in g.graveyard] == ["Grizzly Bears"]


def test_loot_spell_discards_after_drawing():
    g = game(cards(*FILLER))
    loot = Card("Loot", type_line="Sorcery", tags={"draw": 2, "discard": 2})
    g._resolve(loot)
    assert g.hand == [] and len(g.graveyard) == 3  # Loot + two discards


def test_tapped_unless_basic_land():
    palace = Card("Fire Nation Palace", type_line="Land",
                  oracle="This land enters tapped unless you control a basic land.\n{T}: Add {R}.", produced=frozenset("R"))
    tag_card(palace, WUBRG)
    g = game(cards(*FILLER))
    (temple,) = cards("Temple of Mystery")
    g._enter_land(temple, tapped=True)
    assert g.enters_tapped(palace)
    (forest,) = cards("Forest")
    g._enter_land(forest, tapped=False)
    assert not g.enters_tapped(palace)
