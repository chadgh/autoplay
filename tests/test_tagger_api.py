import io
import json
import urllib.error

from autoplay.cards import Card
from autoplay.deck import Deck
from autoplay.sim import scryfall_tags_summary
from autoplay.tagger_api import cached_tags, fetch_tags, parse_card

SOL = {"name": "Sol Ring", "oracle_id": "sol", "set": "cmm", "collector_number": "400"}
SIGNET = {"name": "Arcane Signet", "oracle_id": "sig", "set": "cmm", "collector_number": "401"}
DATA = {"sol ring": SOL, "arcane signet": SIGNET}


def tagging(name, type_="ORACLE_CARD_TAG", ancestors=(), status="GOOD_STANDING"):
    return {"status": status, "tag": {"name": name, "type": type_, "ancestorTags": [{"name": a} for a in ancestors]}}


def test_parse_card_keeps_oracle_tags_and_ancestors():
    card = {
        "taggings": [
            tagging("mana rock", ancestors=["ramp"]),
            tagging("sword", type_="ILLUSTRATION_TAG"),
            tagging("bad", status="REJECTED"),
        ],
        "relationships": [{"classifier": "BETTER_THAN", "name": "Sol Ring", "relatedName": "Mana Vault"}],
    }
    assert parse_card(card) == {
        "tags": ["mana rock", "ramp"],
        "relationships": [{"kind": "BETTER_THAN", "a": "Sol Ring", "b": "Mana Vault"}],
    }


def fake(calls):
    def fetch(set_code, number):
        calls.append(number)
        return {"tags": [f"t{number}"], "relationships": []}

    return fetch


def test_fetch_tags_caches_and_waits_between_requests(tmp_path):
    calls, sleeps = [], []
    cache = tmp_path / "tags.json"
    tags = fetch_tags(DATA, cache, fake(calls), delay=5, sleep=sleeps.append)
    assert tags == {"Sol Ring": {"tags": ["t400"], "relationships": []},
                    "Arcane Signet": {"tags": ["t401"], "relationships": []}}
    assert sleeps == [5]  # no wait before the first request
    fetch_tags(DATA, cache, fake(calls), sleep=sleeps.append)
    assert len(calls) == 2 and cached_tags(DATA, cache) == tags
    fetch_tags(DATA, cache, fake(calls), refresh=True, sleep=lambda s: None)
    assert len(calls) == 4


def test_fetch_tags_skips_failures_and_stops_when_throttled(tmp_path):
    seen = []

    def flaky(set_code, number):
        if number == "401":  # Arcane Signet, fetched first
            raise RuntimeError("boom")
        raise urllib.error.HTTPError("u", 429, "slow down", {}, io.BytesIO())

    tags = fetch_tags({**DATA, "x": {**SOL, "oracle_id": "x", "name": "X", "collector_number": "1"}},
                      tmp_path / "t.json", flaky, sleep=lambda s: None,
                      progress=lambda name, status: seen.append((name, status)))
    assert tags == {}
    assert seen[0] == ("Arcane Signet", "failed: boom")
    assert seen[1][1].startswith("stopped: Tagger returned HTTP 429") and len(seen) == 2


def test_summary_groups_shared_tags_and_in_deck_relationships():
    deck = Deck("d", [Card("Cmdr")], [Card("Sol Ring"), Card("Arcane Signet"), Card("Forest")])
    deck.scryfall_tags = {
        "Sol Ring": {"tags": ["mana rock", "ramp"],
                     "relationships": [{"kind": "BETTER_THAN", "a": "Sol Ring", "b": "Arcane Signet"},
                                       {"kind": "BETTER_THAN", "a": "Sol Ring", "b": "Mana Vault"},
                                       {"kind": "SIMILAR_TO", "a": "Sol Ring", "b": "Sol Ring"}]},
        "Arcane Signet": {"tags": ["cycle-cmm-rock", "mana rock", "ramp", "signet", "triggered ability"], "relationships": []},
        "Cmdr": {"tags": ["ramp"], "relationships": []},
    }
    s = scryfall_tags_summary(deck)
    assert s["shared"] == [["ramp", ["Cmdr", "Sol Ring", "Arcane Signet"]], ["mana rock", ["Sol Ring", "Arcane Signet"]]]
    assert s["relationships"] == [{"kind": "BETTER_THAN", "a": "Sol Ring", "b": "Arcane Signet"}]
    assert s["missing"] == ["Forest"]
    assert s["cards"]["Arcane Signet"] == ["mana rock", "ramp", "signet"]  # trivia tags dropped
    json.dumps(s)
