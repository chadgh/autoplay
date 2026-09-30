"""Auto-tag cards from oracle text.

Tags are {name: int}. Effect tags the engine acts on:
  land, tapped_land, fetch, bounce_land, mana (units per turn), ritual (one-shot units),
  land_to_bf, land_to_hand, land_bf_tapped, draw, upkeep_draw, landfall_draw, tap_draw,
  discard (after each of this card's draws: looting),
  burn (one opponent), drain (each opponent), tutor, tutor_top, haste, extra_land, creature
Role tags used only for stats and pilot decisions:
  ramp, mana_rock, mana_dork, card_draw, interaction, wipe, landfall
"""

from __future__ import annotations

import re

from .cards import Card

NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
LAND_TYPES = ("Plains", "Island", "Swamp", "Mountain", "Forest")
TUTOR_TYPES = ("creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker")
ROLE_TAGS = {"ramp", "mana_rock", "mana_dork", "card_draw", "interaction", "wipe", "creature", "land", "landfall"}

_REMINDER_RE = re.compile(r"\([^)]*\)")
_ABILITY_WORD_RE = re.compile(r"^[A-Z][\w' ]+ — (?=When|At )")  # "Landfall — Whenever ..."
_LANDFALL_RE = re.compile(r"^Whenever a land (?:you control )?enters")
_ADD_RE = re.compile(r"Add ((?:\{[^}]+\})+)")
_ADD_WORDS_RE = re.compile(r"Add (one|two|three) mana")
_DRAW_RE = re.compile(r"\bdraws? (a|one|two|three|four|five|six|seven) cards?", re.IGNORECASE)
_LOOT_RE = re.compile(r"\bdraws? (?:a|one|two|three|four|five|six|seven) cards?, then discards? (a|one|two|three|four|five|six|seven) cards?", re.IGNORECASE)
_SEARCH_RE = re.compile(
    r"[Ss]earch your library for (?:up to )?(a|an|one|two|three)?\s*(.+?) cards?\b(.*)", re.DOTALL
)
_BURN_RE = re.compile(r"deals (\d+) damage to (any target|target player|target opponent|each opponent)")
_LOSE_TARGET_RE = re.compile(r"target (?:player|opponent) loses (\d+) life")
_DRAIN_RE = re.compile(r"each opponent loses (\d+) life")
_INTERACTION_RE = re.compile(
    r"(destroy|exile) target|counter target|return target [^.]* to (its|their) owner's hand"
    r"|deals \d+ damage to target creature",
    re.IGNORECASE,
)
_WIPE_RE = re.compile(r"(destroy|exile) all|deals \d+ damage to each creature|all creatures get -", re.IGNORECASE)


def _lines(card: Card) -> list[str]:
    return [ln.strip() for ln in _REMINDER_RE.sub("", card.oracle).split("\n") if ln.strip()]


def _is_activated(line: str, match_start: int) -> bool:
    colon = line.find(":")
    return 0 <= colon < match_start


def _mana_amount(line: str) -> int:
    amounts = [len(re.findall(r"\{[^}]+\}", m)) for m in _ADD_RE.findall(line)]
    amounts += [NUMBER_WORDS[m] for m in _ADD_WORDS_RE.findall(line)]
    return max(amounts, default=0)


def _activation_generic(line: str) -> int:
    head = line.split(":", 1)[0]
    return sum(int(s) for s in re.findall(r"\{(\d+)\}", head))


def tag_card(card: Card, identity: frozenset) -> Card:
    """Populate card.tags, card.mana_colors and card.search_types in place; returns card."""
    tags: dict[str, int] = {}
    lines = _lines(card)
    text = " ".join(lines)
    front = card.name.split(" // ")[0]
    self_ref = rf"(?:{re.escape(front)}|{re.escape(front.split(',')[0])}|this \w+)"
    allowed = identity | {"C"}

    if card.is_land:
        tags["land"] = 1
    if card.is_creature:
        tags["creature"] = 1
    if "Haste" in card.keywords:
        tags["haste"] = 1

    for line in lines:
        line = _ABILITY_WORD_RE.sub("", line)
        landfall = bool(_LANDFALL_RE.match(line))
        if landfall:
            tags["landfall"] = 1
        # One-shot effects are modeled for spells, ETB triggers, and upkeep triggers.
        triggered = line.startswith("Whenever") or (
            line.startswith("When") and "enters" not in line.split(",")[0]
        )
        upkeep = line.startswith("At the beginning of your upkeep")
        on_tap = bool(re.match(rf"Whenever {self_ref} becomes tapped", line))

        # --- mana abilities
        if "Add " in line and not triggered:
            amount = _mana_amount(line)
            if amount:
                if "Sacrifice" in line.split(":", 1)[0] or not _is_activated(line, line.find("Add ")):
                    tags["ritual"] = max(tags.get("ritual", 0), amount - _activation_generic(line))
                else:
                    net = amount - _activation_generic(line)
                    tags["mana"] = max(tags.get("mana", 0), net)

        # --- enters tapped
        if card.is_land and re.search(r"enters(?: the battlefield)? tapped\.", line) and "If you don't" not in line:
            tags["tapped_land"] = 1
        if "return a land you control to its owner's hand" in line:
            tags["bounce_land"] = 1

        # --- library searches
        m = _SEARCH_RE.search(line)
        if m and not triggered:
            count = NUMBER_WORDS.get((m.group(1) or "a").lower(), 1)
            what, rest = m.group(2), m.group(3)
            if "land" in what or any(t in what for t in LAND_TYPES):
                types = {t for t in LAND_TYPES if t in what}
                card.search_types = frozenset(types or {"basic" if "basic" in what else "land"})
                if "one onto the battlefield" in rest and "the other into your hand" in rest:
                    tags["land_to_bf"], tags["land_to_hand"] = 1, count - 1
                    tags["land_bf_tapped"] = int("battlefield tapped" in rest)
                elif "onto the battlefield" in rest:
                    tags["land_to_bf"] = count
                    tags["land_bf_tapped"] = int("battlefield tapped" in rest)
                else:
                    tags["land_to_hand"] = count
                if card.is_land and "Sacrifice" in line and _activation_generic(line) == 0:
                    tags["fetch"] = 1
            else:
                tags["tutor"] = 1
                card.search_types = frozenset(t for t in TUTOR_TYPES if t in what.lower())
                if "on top" in rest:
                    tags["tutor_top"] = 1

        # --- card draw
        m = _DRAW_RE.search(line)
        if m and landfall:
            tags["landfall_draw"] = NUMBER_WORDS[m.group(1).lower()]
        elif m and on_tap:
            tags["tap_draw"] = NUMBER_WORDS[m.group(1).lower()]
        elif m and not triggered and not _is_activated(line, m.start()):
            n = NUMBER_WORDS[m.group(1).lower()]
            tags["upkeep_draw" if upkeep else "draw"] = n
        else:
            m = None
        loot = m and _LOOT_RE.search(line)
        if loot:
            tags["discard"] = NUMBER_WORDS[loot.group(1).lower()]

        # --- damage / life loss
        if not triggered and not upkeep:
            for amount, target in _BURN_RE.findall(line):
                tags["drain" if target == "each opponent" else "burn"] = int(amount)
            for amount in _LOSE_TARGET_RE.findall(line):
                tags["burn"] = tags.get("burn", 0) + int(amount)
            for amount in _DRAIN_RE.findall(line):
                tags["drain"] = tags.get("drain", 0) + int(amount)

        if "play an additional land" in line:
            tags["extra_land"] = 1

    if _INTERACTION_RE.search(text):
        tags["interaction"] = 1
    if _WIPE_RE.search(text):
        tags["wipe"] = 1

    # --- roles
    if not card.is_land:
        if tags.get("mana", 0) > 0:
            tags["mana_dork" if card.is_creature else "mana_rock"] = 1
        if tags.get("mana", 0) > 0 or tags.get("ritual", 0) > 0 or "land_to_bf" in tags or "land_to_hand" in tags:
            tags["ramp"] = 1
        if "draw" in tags or "upkeep_draw" in tags or "landfall_draw" in tags or "tap_draw" in tags:
            tags["card_draw"] = 1
    elif "mana" not in tags and "fetch" not in tags:
        tags["mana"] = 1 if card.produced else 0

    tags = {k: v for k, v in tags.items() if v > 0}
    card.tags = tags
    card.mana_colors = _mana_colors(card, allowed, identity)
    return card


def _mana_colors(card: Card, allowed: frozenset, identity: frozenset) -> frozenset:
    if "commander's color identity" in card.oracle:
        return identity or frozenset("C")
    colors = card.produced & allowed
    return colors or (frozenset("C") if card.produced else frozenset())


def is_untagged(card: Card) -> bool:
    """Nonland card with rules text the engine doesn't model."""
    if card.is_land:
        return False
    if set(card.tags) - ROLE_TAGS:
        return False
    if card.tags.get("interaction") or card.tags.get("wipe"):
        return False  # removal is held in a goldfish game, which is what we model
    text = " ".join(_lines(card))
    keyword_only = all(w.strip(" ,").lower() in {k.lower() for k in card.keywords} for w in text.split(",")) if text else True
    return not keyword_only
