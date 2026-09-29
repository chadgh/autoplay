import json
from pathlib import Path

import pytest

from autoplay.cards import card_from_scryfall, fetch_card_data, parse_decklist

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cards.json").read_text())


def by_name(name):
    return next(c for c in FIXTURE if c["name"].startswith(name))


def test_parse_moxfield():
    text = """Commander
1 Kenrith, the Returned King (ELD) 303

Deck
1 Sol Ring (CMM) 400 *F*
10 Forest
1x Cultivate

SIDEBOARD:
1 Lightning Bolt
"""
    entries = parse_decklist(text)
    assert [(e.name, e.count, e.commander) for e in entries] == [
        ("Kenrith, the Returned King", 1, True),
        ("Sol Ring", 1, False),
        ("Forest", 10, False),
        ("Cultivate", 1, False),
    ]


def test_parse_archidekt_tags():
    text = "1x Kenrith, the Returned King (eld) 303 [Commander{top}]\n1x Sol Ring (cmm) 400 [Ramp]\n"
    entries = parse_decklist(text)
    assert entries[0].commander and not entries[1].commander
    assert entries[1].name == "Sol Ring"


def test_parse_cmdr_marker():
    assert parse_decklist("1 Kenrith, the Returned King *CMDR*")[0].commander


def test_card_from_scryfall_basic():
    card = card_from_scryfall(by_name("Grizzly Bears"))
    assert card.is_creature and card.power == 2 and card.cost.total == 2


def test_card_from_scryfall_mdfc_land():
    card = card_from_scryfall(by_name("Shatterskull Smashing"))
    assert card.is_land and card.cost.total == 0


def test_card_from_scryfall_transform_front():
    card = card_from_scryfall(by_name("Delver of Secrets"))
    assert card.is_creature and card.power == 1


def test_fetch_uses_cache(tmp_path):
    calls = []

    def fake_fetch(names):
        calls.append(names)
        return {"data": [by_name(n) for n in names], "not_found": []}

    cache = tmp_path / "cards.json"
    fetch_card_data(["Sol Ring", "Forest"], cache, fake_fetch)
    data = fetch_card_data(["Sol Ring", "Forest"], cache, fake_fetch)
    assert len(calls) == 1 and data["sol ring"]["name"] == "Sol Ring"


def test_fetch_reports_missing(tmp_path):
    with pytest.raises(LookupError, match="Nope"):
        fetch_card_data(["Nope"], tmp_path / "c.json", lambda n: {"data": [], "not_found": [{"name": "Nope"}]})
