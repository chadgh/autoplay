"""Decision-making for the goldfish player. GreedyPilot is a simple heuristic;
other pilots only need to implement the same methods."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .cards import Card, matches_search
from .mana import solve_payment

if TYPE_CHECKING:
    from .game import Game, Permanent


class Pilot(Protocol):
    def keep(self, hand: list[Card], mulligans: int) -> bool: ...
    def bottom(self, hand: list[Card], n: int) -> list[Card]: ...
    def main_phase(self, game: "Game") -> None: ...
    def discard(self, game: "Game", n: int) -> list[Card]: ...
    def choose_search_land(self, game: "Game", candidates: list[Card]) -> Card: ...
    def choose_tutor(self, game: "Game", candidates: list[Card]) -> Card | None: ...
    def choose_bounce(self, game: "Game", lands: list["Permanent"]) -> "Permanent": ...


def _is_ramp(card: Card) -> bool:
    t = card.tags
    return bool(t.get("mana") or t.get("land_to_bf") or t.get("land_to_hand")) and not card.is_land


def _is_dead_in_goldfish(card: Card) -> bool:
    """Removal/counters/wipes with nothing else to do: hold them."""
    t = card.tags
    effects = set(t) - {"interaction", "wipe", "creature"}
    return not card.is_permanent and ("interaction" in t or "wipe" in t) and not effects


class GreedyPilot:
    def __init__(self, keep_min: int = 2, keep_max: int = 5, max_mulligans: int = 2):
        self.keep_min, self.keep_max, self.max_mulligans = keep_min, keep_max, max_mulligans

    # ------------------------------------------------------------ mulligans

    def keep(self, hand: list[Card], mulligans: int) -> bool:
        if mulligans >= self.max_mulligans:
            return True
        lands = sum(c.is_land for c in hand)
        return self.keep_min <= lands <= self.keep_max

    def bottom(self, hand: list[Card], n: int) -> list[Card]:
        rest = list(hand)
        out: list[Card] = []
        for _ in range(n):
            lands = [c for c in rest if c.is_land]
            spells = sorted((c for c in rest if not c.is_land), key=lambda c: -c.cmc)
            pick = lands[-1] if (len(lands) > 3 or not spells) else spells[0]
            rest.remove(pick)
            out.append(pick)
        return out

    # ------------------------------------------------------------ main phase

    def main_phase(self, game: "Game") -> None:
        while True:
            self._play_lands(game)
            card = self._next_spell(game)
            if card is None:
                break
            game.cast(card)

    def _play_lands(self, game: "Game") -> None:
        while game.can_play_land():
            lands = [c for c in game.hand if c.is_land]
            if not lands:
                return
            game.play_land(max(lands, key=lambda c: self._land_score(game, c)))

    def _needed_colors(self, game: "Game") -> frozenset:
        cards = [c for c in game.hand if not c.is_land] + game.command
        needed = frozenset().union(*(p for c in cards for p in c.cost.pips)) if cards else frozenset()
        return needed - game.source_colors()

    def _land_score(self, game: "Game", land: Card) -> float:
        colors = land.mana_colors
        if land.tags.get("fetch"):
            found = [c for c in game.library if c.is_land and matches_search(c, land.search_types)]
            colors = frozenset().union(*(c.mana_colors for c in found)) if found else frozenset()
        score = 10 * len(colors & self._needed_colors(game))
        if land.tags.get("bounce_land") and not game.lands():
            return -100
        if land.tags.get("tapped_land"):
            # Tapped lands are best on turns where the extra mana wouldn't be used.
            score += 0 if self._untapped_unlocks(game, land) else 3
        else:
            score += 2 + (5 if self._untapped_unlocks(game, land) else 0)
        return score

    def _untapped_unlocks(self, game: "Game", land: Card) -> bool:
        pool = game.pool + [land.mana_colors or frozenset("C")] * max(1, land.tags.get("mana", 1))
        for c in self._candidates(game):
            if c is land:
                continue
            cost = game.cost_of(c)
            if solve_payment(cost, game.pool) is None and solve_payment(cost, pool) is not None:
                return True
        return False

    def _candidates(self, game: "Game") -> list[Card]:
        return [c for c in game.hand if not c.is_land and not _is_dead_in_goldfish(c)] + list(game.command)

    def _priority(self, card: Card) -> tuple:
        if card.tags.get("ritual"):
            return (4, 0)
        if _is_ramp(card):
            return (0, card.cmc)
        if card.tags.get("draw") or card.tags.get("upkeep_draw"):
            return (1, card.cmc)
        if card.is_commander:
            return (2, 0)
        return (3, -card.cmc)

    def _next_spell(self, game: "Game") -> Card | None:
        for card in sorted(self._candidates(game), key=self._priority):
            if not game.can_cast(card):
                continue
            if card.tags.get("ritual") and not self._ritual_helps(game, card):
                continue
            return card
        return None

    def _ritual_helps(self, game: "Game", ritual: Card) -> bool:
        cost = game.cost_of(ritual)
        paid = solve_payment(cost, game.pool)
        pool = [u for i, u in enumerate(game.pool) if i not in set(paid)]
        pool += [ritual.mana_colors or frozenset("C")] * ritual.tags["ritual"]
        others = [c for c in self._candidates(game) if c is not ritual and not c.tags.get("ritual")]
        return any(solve_payment(game.cost_of(c), pool) is not None for c in others)

    # ------------------------------------------------------------ choices

    def discard(self, game: "Game", n: int) -> list[Card]:
        # With plenty of lands out, pitch extra lands first; otherwise the most expensive spells.
        flooded = len(game.lands()) >= 6
        lands = [c for c in game.hand if c.is_land]
        spells = sorted((c for c in game.hand if not c.is_land), key=lambda c: -c.cmc)
        return (lands + spells if flooded else spells + lands)[:n]

    def choose_search_land(self, game: "Game", candidates: list[Card]) -> Card:
        needed = self._needed_colors(game)
        return max(candidates, key=lambda c: (len(c.mana_colors & needed), not c.tags.get("tapped_land"), len(c.mana_colors)))

    def choose_tutor(self, game: "Game", candidates: list[Card]) -> Card | None:
        owned = {c.name for c in game.hand} | {p.card.name for p in game.battlefield}
        keys = [c for c in candidates if c.key and c.name not in owned]
        if keys:
            return keys[0]
        spells = [c for c in candidates if not c.is_land]
        if not spells:
            return None
        if len(game.lands()) < 5:
            ramp = [c for c in spells if _is_ramp(c)]
            if ramp:
                return min(ramp, key=lambda c: c.cmc)
        return max(spells, key=lambda c: (c.power, c.cmc))

    def choose_bounce(self, game: "Game", lands: list["Permanent"]) -> "Permanent":
        # Return a land that's already been tapped for mana this turn (or a basic).
        return min(lands, key=lambda p: (not p.tapped, "Basic" not in p.card.type_line, -len(p.card.mana_colors)))
