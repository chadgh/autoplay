import json
from pathlib import Path

import pytest

from autoplay.cards import Card, card_from_scryfall
from autoplay.tagger import is_untagged, tag_card

FIXTURE = {c["name"].split(" // ")[0]: c for c in json.loads((Path(__file__).parent / "fixtures" / "cards.json").read_text())}
GU = frozenset("GU")


def tagged(name, identity=GU):
    return tag_card(card_from_scryfall(FIXTURE[name]), identity)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Sol Ring", {"mana": 2, "mana_rock": 1, "ramp": 1}),
        ("Llanowar Elves", {"mana": 1, "mana_dork": 1, "ramp": 1, "creature": 1}),
        ("Cultivate", {"land_to_bf": 1, "land_to_hand": 1, "land_bf_tapped": 1, "ramp": 1}),
        ("Rampant Growth", {"land_to_bf": 1, "land_bf_tapped": 1, "ramp": 1}),
        ("Nature's Lore", {"land_to_bf": 1, "ramp": 1}),
        ("Harmonize", {"draw": 3, "card_draw": 1}),
        ("Night's Whisper", {"draw": 2, "card_draw": 1}),
        ("Phyrexian Arena", {"upkeep_draw": 1, "card_draw": 1}),
        ("Lightning Bolt", {"burn": 3}),
        ("Demonic Tutor", {"tutor": 1}),
        ("Swords to Plowshares", {"interaction": 1}),
        ("Counterspell", {"interaction": 1}),
        ("Wrath of God", {"wipe": 1}),
        ("Forest", {"land": 1, "mana": 1}),
        ("Command Tower", {"land": 1, "mana": 1}),
        ("Temple of Mystery", {"land": 1, "mana": 1, "tapped_land": 1}),
        ("Breeding Pool", {"land": 1, "mana": 1}),
        ("Simic Growth Chamber", {"land": 1, "mana": 2, "tapped_land": 1, "bounce_land": 1}),
        ("Evolving Wilds", {"land": 1, "fetch": 1, "land_to_bf": 1, "land_bf_tapped": 1}),
        ("Windswept Heath", {"land": 1, "fetch": 1, "land_to_bf": 1}),
        ("Wood Elves", {"creature": 1, "land_to_bf": 1, "ramp": 1}),
        ("Solemn Simulacrum", {"creature": 1, "land_to_bf": 1, "land_bf_tapped": 1, "ramp": 1}),
        ("Explore", {"extra_land": 1, "draw": 1, "card_draw": 1}),
        ("Dark Ritual", {"ritual": 3, "ramp": 1}),
        ("Mind Stone", {"mana": 1, "mana_rock": 1, "ramp": 1}),
        ("Goblin Guide", {"creature": 1, "haste": 1}),
        ("Grizzly Bears", {"creature": 1}),
    ],
)
def test_tags(name, expected):
    assert tagged(name).tags == expected


def test_mana_colors():
    assert tagged("Command Tower").mana_colors == GU
    assert tagged("Arcane Signet").mana_colors == GU
    assert tagged("Sol Ring").mana_colors == frozenset("C")
    assert tagged("Birds of Paradise").mana_colors == GU


def test_search_types():
    assert tagged("Cultivate").search_types == frozenset({"basic"})
    assert tagged("Windswept Heath").search_types == frozenset({"Forest", "Plains"})


def test_untagged():
    assert is_untagged(tagged("Blood Artist"))
    assert is_untagged(tagged("Thassa's Oracle"))
    assert not is_untagged(tagged("Grizzly Bears"))
    assert not is_untagged(tagged("Sol Ring"))
    assert not is_untagged(tagged("Forest"))


def test_landfall_draw_is_not_one_shot():
    assert tagged("Aesi, Tyrant of Gyre Strait").tags == {"creature": 1, "extra_land": 1, "landfall_draw": 1, "landfall": 1, "card_draw": 1}
    assert tagged("Tatyova, Benthic Druid").tags == {"creature": 1, "landfall_draw": 1, "landfall": 1, "card_draw": 1}


def test_paid_fetch_is_just_a_land():
    tags = tagged("Myriad Landscape").tags
    assert "fetch" not in tags and tags["tapped_land"] == 1 and tags["mana"] == 1


def test_tutor_restrictions():
    mystical = tagged("Mystical Tutor")
    assert mystical.tags == {"tutor": 1, "tutor_top": 1}
    assert mystical.search_types == frozenset({"instant", "sorcery"})
    assert tagged("Worldly Tutor").search_types == frozenset({"creature"})
    assert tagged("Demonic Tutor").search_types == frozenset()


def test_held_interaction_is_modeled():
    assert not is_untagged(tagged("Counterspell"))
    assert not is_untagged(tagged("Cyclonic Rift"))
    assert not is_untagged(tagged("Ravenous Chupacabra"))


def test_tap_draw():
    assert tagged("Gran-Gran").tags == {"creature": 1, "tap_draw": 1, "discard": 1, "card_draw": 1}


def test_loot_spell():
    card = card_from_scryfall({"name": "Loot", "type_line": "Sorcery", "mana_cost": "{R}", "cmc": 1,
                               "oracle_text": "Draw two cards, then discard two cards."})
    assert tag_card(card, GU).tags == {"draw": 2, "discard": 2, "card_draw": 1}


@pytest.mark.parametrize(
    "text, untapped_if",
    [
        ("This land enters tapped unless you control a basic land.", (1, frozenset({"basic"}))),
        ("This land enters tapped unless you control two or more basic lands.", (2, frozenset({"basic"}))),
        ("This land enters tapped unless you control two or more other lands.", (2, frozenset({"land"}))),
        ("This land enters tapped unless you control a Forest or an Island.", (1, frozenset({"Forest", "Island"}))),
        ("This land enters tapped unless you control three or more other Plains.", (3, frozenset({"Plains"}))),
    ],
)
def test_conditional_tapped_lands(text, untapped_if):
    card = tag_card(Card("Test Land", type_line="Land", oracle=text + "\n{T}: Add {G}.", produced=frozenset("G")), GU)
    assert card.tags == {"land": 1, "mana": 1, "tapped_land": 1}
    assert card.untapped_if == untapped_if


def test_opponent_count_condition_enters_untapped():
    text = "This land enters tapped unless you have two or more opponents.\n{T}: Add {G}."
    card = tag_card(Card("Test Land", type_line="Land", oracle=text, produced=frozenset("G")), GU)
    assert "tapped_land" not in card.tags
