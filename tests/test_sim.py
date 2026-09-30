import json
from math import comb
from pathlib import Path

import pytest

from autoplay.cards import parse_decklist
from autoplay.deck import build_deck
from autoplay.overrides import Overrides
from autoplay.sim import simulate

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cards.json").read_text())
DATA = {}
for c in FIXTURE:
    DATA[c["name"].lower()] = c
    DATA[c["name"].split(" // ")[0].lower()] = c

DECKLIST = """Commander
1 Kenrith, the Returned King

Deck
1 Sol Ring
1 Arcane Signet
1 Llanowar Elves
1 Cultivate
1 Rampant Growth
1 Harmonize
1 Night's Whisper
1 Lightning Bolt
1 Goblin Guide
1 Demonic Tutor
1 Swords to Plowshares
1 Wrath of God
1 Thassa's Oracle
1 Blood Artist
1 Command Tower
1 Evolving Wilds
1 Temple of Mystery
7 Forest
7 Mountain
7 Plains
7 Island
7 Swamp
47 Grizzly Bears
"""


@pytest.fixture(scope="module")
def deck():
    return build_deck("test", parse_decklist(DECKLIST), DATA, Overrides(key_cards={"thassa's oracle"}))


def test_deck_build(deck):
    assert [c.name for c in deck.commanders] == ["Kenrith, the Returned King"]
    assert len(deck.library) == 99
    assert deck.identity == frozenset("WUBRG")
    assert "Blood Artist" in deck.untagged()
    assert deck.key_cards() == ["Thassa's Oracle"]
    assert deck.off_identity() == []  # Kenrith is five-color


@pytest.fixture(scope="module")
def result(deck):
    return simulate(deck, n=400, turns=8, seed=7)


def test_result_is_json_serializable(result):
    json.dumps(result)


def test_seed_is_reproducible(deck):
    a = simulate(deck, n=30, turns=5, seed=3, baseline=False)
    b = simulate(deck, n=30, turns=5, seed=3, baseline=False)
    assert a == b


def test_random_baseline_matches_hypergeometric(result):
    # 38 lands (35 basics + 3) in 99: expected lands in a random opening 7 = 7 * 38 / 99.
    expected = 7 * 38 / 99
    assert abs(result["random"]["shuffle"]["opening_lands_mean"] - expected) < 0.25


def test_stats_are_sane(result):
    human = result["human"]
    per_turn = human["per_turn"]
    assert len(per_turn["lands"]) == 8
    assert per_turn["lands"] == sorted(per_turn["lands"])  # lands never decrease on average
    assert all(0 <= p <= 1 for p in per_turn["land_drop_pct"])
    assert all(s <= a + 1e-9 for s, a in zip(per_turn["mana_spent"], per_turn["mana_available"]))
    assert human["commander_turn"]["median"] is not None
    oracle = human["key_cards"]["Thassa's Oracle"]
    assert oracle == sorted(oracle) and 0 < oracle[-1] < 1


def test_off_identity_warning():
    text = "Commander\n1 Aesi, Tyrant of Gyre Strait\nDeck\n1 Lightning Bolt\n1 Forest\n"
    deck = build_deck("t", parse_decklist(text), DATA, Overrides())
    assert deck.off_identity() == ["Lightning Bolt"]


def test_average_hand_is_a_typical_kept_hand(result):
    hand = result["human"]["average_hand"]
    names = hand["cards"]
    assert len(names) == hand["profile"]["cards"] <= 7
    assert hand["profile"]["lands"] == sum(n in {"Forest", "Mountain", "Plains", "Island", "Swamp", "Command Tower",
                                                 "Evolving Wilds", "Temple of Mystery"} for n in names)
    assert abs(hand["profile"]["lands"] - hand["mean"]["lands"]) <= 1


def test_search_shuffle_is_configurable(deck):
    r = simulate(deck, n=5, turns=3, seed=1, baseline=False, search_shuffle="riffle x3, cut")
    assert r["settings"]["search_shuffle"] == "riffle x3, cut"
    with pytest.raises(ValueError):
        simulate(deck, n=1, turns=1, baseline=False, search_shuffle="shimmy")


def test_deck_identity_is_in_wubrg_order(deck):
    r = simulate(deck, n=1, turns=1, seed=1, baseline=False)
    assert r["deck"]["identity"] == ["W", "U", "B", "R", "G"]  # Kenrith


def test_first_game_log_accounts_for_every_card(result):
    g = result["human"]["first_game"]
    assert [t["turn"] for t in g["turns"]] == list(range(1, 9))
    assert len(g["opening_hand"]) == 7 - max(0, g["mulligans"] - 1)
    # Every card played came from the opening hand or was drawn/searched by then (commanders from the command zone).
    hand = list(g["opening_hand"])
    for t in g["turns"]:
        assert sorted(t["hand"]) == sorted(hand), t["turn"]  # the start-of-turn hand matches the log so far
        hand += t["drawn"] + [s["card"] for s in t["searched"] if s["to"] == "hand"]
        for p in t["played"]:
            if p["how"] != "commander":
                assert p["card"] in hand, (t["turn"], p["card"])
                hand.remove(p["card"])
        for name in t["discarded"]:
            hand.remove(name)
        assert len(hand) == t["hand_size"]
        assert t["lands"] >= 0 and t["spent"] <= t["mana"]
    assert sum(len(t["drawn"]) for t in g["turns"]) >= 8  # at least one draw per turn


def test_decklist_printing_sets_image_and_link_only():
    text = "Commander\n1 Kenrith, the Returned King\nDeck\n2 Sol Ring (CMM) 400\n1 Forest\n"
    printing = {**DATA["sol ring"], "image_uris": {"normal": "https://img/cmm-400.jpg"},
                "scryfall_uri": "https://scryfall.com/card/cmm/400/sol-ring?utm_source=api", "oracle_text": "changed"}
    deck = build_deck("t", parse_decklist(text), DATA, Overrides(), printings={("cmm", "400"): printing})
    rings = [c for c in deck.library if c.name == "Sol Ring"]
    assert len(rings) == 2 and all(c.image_uri == "https://img/cmm-400.jpg" for c in rings)
    assert rings[0].scryfall_uri == "https://scryfall.com/card/cmm/400/sol-ring"
    assert rings[0].oracle == DATA["sol ring"]["oracle_text"]  # game data still comes from the name lookup


def test_decklist_printing_of_another_card_is_ignored():
    text = "Commander\n1 Kenrith, the Returned King\nDeck\n1 Sol Ring (CMM) 400\n"
    wrong = {**DATA["forest"], "image_uris": {"normal": "https://img/forest.jpg"}}
    deck = build_deck("t", parse_decklist(text), DATA, Overrides(), printings={("cmm", "400"): wrong})
    assert deck.library[0].image_uri != "https://img/forest.jpg"
