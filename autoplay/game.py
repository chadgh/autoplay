"""Goldfish game engine: zones, turn structure, casting and effect resolution.

Mana model: at the start of each main phase every available source is tapped
into a floating pool of units (see mana.py). New sources that can be used the
same turn (untapped lands, rocks, rituals) add units immediately.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import Card, matches_search
from .mana import Cost, color_screwed, solve_payment
from .shuffle import Step, parse_routine, run_routine
from .stats import GameRecord

DEFAULT_GATHER = ("library", "hand", "graveyard", "nonlands", "lands")


@dataclass
class GameConfig:
    turns: int = 10
    shuffle: list[Step] = field(default_factory=lambda: parse_routine("mash x2, cut"))
    search_shuffle: list[Step] = field(default_factory=lambda: parse_routine("mash x2, cut"))
    gather_order: tuple[str, ...] = DEFAULT_GATHER
    draw_first_turn: bool = True  # multiplayer: nobody skips their first draw
    opponents: int = 3
    life: int = 40
    commander_damage: int = 21


@dataclass(eq=False)
class Permanent:
    card: Card
    tapped: bool = False
    sick: bool = False


class Game:
    def __init__(self, library: list[Card], commanders: list[Card], pilot, config: GameConfig, rng: random.Random):
        self.library = list(library)  # index 0 is the top
        self.hand: list[Card] = []
        self.battlefield: list[Permanent] = []
        self.graveyard: list[Card] = []
        self.command: list[Card] = list(commanders)
        self.casts: dict[int, int] = {}  # id(commander) -> times cast, for tax
        self.pilot = pilot
        self.config = config
        self.rng = rng
        self.turn = 0
        self.pool: list[frozenset] = []
        self.turn_units: list[frozenset] = []
        self.lands_played = 0
        self.land_drops = 1
        self.damage = 0  # to a single opponent
        self.pod_damage = 0  # summed over all opponents
        self.cmd_damage = 0
        self.spent = 0
        self.record = GameRecord()

    # ------------------------------------------------------------ setup

    def shuffle_library(self, steps: list[Step]) -> None:
        self.library = run_routine(self.library, steps, self.rng)

    def start(self) -> None:
        self.shuffle_library(self.config.shuffle)
        self.record.note_shuffle(self.library)
        mulligans = 0
        while True:
            self.hand, self.library = self.library[:7], self.library[7:]
            if mulligans == 0:
                self.record.opening_lands = sum(c.is_land for c in self.hand)
            if self.pilot.keep(self.hand, mulligans):
                break
            mulligans += 1
            self.library = self.hand + self.library
            self.hand = []
            self.shuffle_library(self.config.shuffle)
        to_bottom = max(0, mulligans - 1)  # first mulligan is free in Commander
        for card in self.pilot.bottom(self.hand, to_bottom):
            self.hand.remove(card)
            self.library.append(card)
        self.record.mulligans = mulligans
        self.record.note_opening_hand(self.hand)
        for card in self.hand:
            self.record.see(card, 0)

    # ------------------------------------------------------------ helpers

    def cost_of(self, card: Card) -> Cost:
        if card.is_commander:
            return card.cost.plus(2 * self.casts.get(id(card), 0))
        return card.cost

    def can_cast(self, card: Card) -> bool:
        return solve_payment(self.cost_of(card), self.pool) is not None

    def can_play_land(self) -> bool:
        return self.lands_played < self.land_drops

    def lands(self) -> list[Permanent]:
        return [p for p in self.battlefield if p.card.is_land]

    def source_colors(self) -> frozenset:
        return frozenset().union(*(p.card.mana_colors for p in self.battlefield if p.card.tags.get("mana")))

    def _add_units(self, card: Card, n: int) -> None:
        units = [card.mana_colors or frozenset("C")] * n
        self.pool += units
        self.turn_units += units

    def _to_hand(self, card: Card) -> None:
        self.hand.append(card)
        self.record.see(card, self.turn)

    def draw(self, n: int = 1) -> None:
        for _ in range(n):
            if not self.library:
                return
            self._to_hand(self.library.pop(0))

    # ------------------------------------------------------------ actions

    def play_land(self, card: Card) -> None:
        assert self.can_play_land() and card.is_land
        self.hand.remove(card)
        self.lands_played += 1
        self.record.mark_land_drop()
        if card.tags.get("fetch"):
            self.graveyard.append(card)
            self._search_lands(card)
            return
        self._enter_land(card, tapped=bool(card.tags.get("tapped_land")))
        if card.tags.get("bounce_land"):
            others = [p for p in self.lands() if p.card is not card]
            if others:
                back = self.pilot.choose_bounce(self, others)
                self.battlefield.remove(back)
                self.hand.append(back.card)

    def _enter_land(self, card: Card, tapped: bool) -> None:
        self.battlefield.append(Permanent(card, tapped=tapped))
        if not tapped and card.tags.get("mana"):
            self._add_units(card, card.tags["mana"])
        for p in self.battlefield:
            if p.card.tags.get("landfall_draw"):
                self.draw(p.card.tags["landfall_draw"])

    def cast(self, card: Card) -> None:
        cost = self.cost_of(card)
        paid = solve_payment(cost, self.pool)
        assert paid is not None, f"cannot pay for {card.name}"
        for i in sorted(paid, reverse=True):
            self.pool.pop(i)
        self.spent += cost.total
        if card.is_commander:
            self.command.remove(card)
            self.casts[id(card)] = self.casts.get(id(card), 0) + 1
            self.record.commander_cast(self.turn)
        else:
            self.hand.remove(card)
        self._resolve(card)

    def _resolve(self, card: Card) -> None:
        t = card.tags
        if t.get("ritual"):
            self._add_units(card, t["ritual"])
            self.graveyard.append(card)
        elif card.is_permanent:
            sick = card.is_creature and not t.get("haste")
            self.battlefield.append(Permanent(card, sick=sick))
            if t.get("mana") and not card.is_creature:
                self._add_units(card, t["mana"])
            if t.get("extra_land"):
                self.land_drops += t["extra_land"]
        else:
            self.graveyard.append(card)
            if t.get("extra_land"):
                self.land_drops += t["extra_land"]
        if t.get("land_to_bf") or t.get("land_to_hand"):
            self._search_lands(card)
        if t.get("tutor"):
            found = [c for c in self.library if _tutorable(c, card.search_types)]
            target = self.pilot.choose_tutor(self, found)
            if target is not None:
                self.library.remove(target)
            self.shuffle_library(self.config.search_shuffle)
            if target is not None:
                if t.get("tutor_top"):
                    self.library.insert(0, target)
                else:
                    self._to_hand(target)
        if t.get("draw"):
            self.draw(t["draw"])
        self._deal(t.get("burn", 0), t.get("drain", 0))

    def _search_lands(self, card: Card) -> None:
        t = card.tags
        for dest, n in (("bf", t.get("land_to_bf", 0)), ("hand", t.get("land_to_hand", 0))):
            for _ in range(n):
                found = [c for c in self.library if matches_search(c, card.search_types)]
                if not found:
                    break
                choice = self.pilot.choose_search_land(self, found)
                self.library.remove(choice)
                if dest == "bf":
                    self._enter_land(choice, tapped=bool(t.get("land_bf_tapped") or choice.tags.get("tapped_land")))
                else:
                    self._to_hand(choice)
        self.shuffle_library(self.config.search_shuffle)

    def _deal(self, single: int, each: int, commander: int = 0) -> None:
        self.damage += single + each
        self.pod_damage += single + each * self.config.opponents
        self.cmd_damage += commander

    # ------------------------------------------------------------ turn

    def take_turn(self) -> None:
        self.turn += 1
        self.lands_played = 0
        self.land_drops = 1 + sum(p.card.tags.get("extra_land", 0) for p in self.battlefield if p.card.is_permanent)
        self.spent = 0
        for p in self.battlefield:
            p.tapped = p.sick = False
        for p in self.battlefield:
            if p.card.tags.get("upkeep_draw"):
                self.draw(p.card.tags["upkeep_draw"])
        if self.turn > 1 or self.config.draw_first_turn:
            self.draw()

        self.pool, self.turn_units = [], []
        for p in self.battlefield:
            if p.card.tags.get("mana") and not p.tapped and not p.sick:
                self._add_units(p.card, p.card.tags["mana"])

        self.pilot.main_phase(self)
        self._combat()

        excess = len(self.hand) - 7
        if excess > 0:
            for card in self.pilot.discard(self, excess):
                self.hand.remove(card)
                self.graveyard.append(card)
        self._record_turn()

    def _combat(self) -> None:
        for p in self.battlefield:
            if p.card.is_creature and not p.sick and p.card.power > 0:
                self._deal(p.card.power, 0, p.card.power if p.card.is_commander else 0)

    def _record_turn(self) -> None:
        stuck = [c for c in self.hand if not c.is_land] + self.command
        screwed = any(color_screwed(self.cost_of(c), self.turn_units) for c in stuck)
        cfg = self.config
        self.record.end_turn(
            turn=self.turn,
            lands=len(self.lands()),
            mana=len(self.turn_units),
            spent=self.spent,
            screwed=screwed,
            damage=self.damage,
            pod_damage=self.pod_damage,
            hand=len(self.hand),
            kill1=self.damage >= cfg.life or self.cmd_damage >= cfg.commander_damage,
            kill_pod=self.pod_damage >= cfg.life * cfg.opponents,
        )

    def play(self) -> GameRecord:
        self.start()
        for _ in range(self.config.turns):
            self.take_turn()
        return self.record

    # ------------------------------------------------------------ cleanup

    def gather(self) -> list[Card]:
        """Pick the cards up in piles (top to bottom) for the next game's pre-shuffle order."""
        piles = {
            "library": self.library,
            "hand": self.hand,
            "graveyard": self.graveyard,
            "nonlands": [p.card for p in self.battlefield if not p.card.is_land and not p.card.is_commander],
            "lands": [p.card for p in self.battlefield if p.card.is_land],
        }
        return [c for name in self.config.gather_order for c in piles[name]]



def _tutorable(card: Card, types: frozenset) -> bool:
    return not types or any(t in card.type_line.lower() for t in types)
