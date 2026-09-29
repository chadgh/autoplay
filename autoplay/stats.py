"""Per-game records and aggregation into a JSON-serializable summary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import mean, median, pvariance

from .cards import Card

ROLES = ("ramp", "card_draw", "tutor", "interaction", "wipe")


@dataclass
class GameRecord:
    mulligans: int = 0
    opening_lands: int = 0
    longest_land_run: int = 0  # in the top 20 cards right after the shuffle
    commander_turn: int | None = None
    kill1_turn: int | None = None
    kill_pod_turn: int | None = None
    first_seen: dict[str, int] = field(default_factory=dict)  # card name -> turn (0 = opening hand)
    role_seen: dict[str, int] = field(default_factory=dict)
    lands: list[int] = field(default_factory=list)
    land_drop: list[bool] = field(default_factory=list)
    mana: list[int] = field(default_factory=list)
    spent: list[int] = field(default_factory=list)
    screwed: list[bool] = field(default_factory=list)
    damage: list[int] = field(default_factory=list)
    pod_damage: list[int] = field(default_factory=list)
    hand: list[int] = field(default_factory=list)
    _drop_this_turn: bool = False

    def note_shuffle(self, library: list[Card]) -> None:
        run = best = 0
        for card in library[:20]:
            run = run + 1 if card.is_land else 0
            best = max(best, run)
        self.longest_land_run = best

    def see(self, card: Card, turn: int) -> None:
        self.first_seen.setdefault(card.name, turn)
        for role in ROLES:
            if card.tags.get(role):
                self.role_seen.setdefault(role, turn)

    def mark_land_drop(self) -> None:
        self._drop_this_turn = True

    def commander_cast(self, turn: int) -> None:
        if self.commander_turn is None:
            self.commander_turn = turn

    def end_turn(self, *, turn, lands, mana, spent, screwed, damage, pod_damage, hand, kill1, kill_pod) -> None:
        self.lands.append(lands)
        self.land_drop.append(self._drop_this_turn)
        self._drop_this_turn = False
        self.mana.append(mana)
        self.spent.append(spent)
        self.screwed.append(screwed)
        self.damage.append(damage)
        self.pod_damage.append(pod_damage)
        self.hand.append(hand)
        if kill1 and self.kill1_turn is None:
            self.kill1_turn = turn
        if kill_pod and self.kill_pod_turn is None:
            self.kill_pod_turn = turn


def _per_turn_mean(records: list[GameRecord], attr: str) -> list[float]:
    turns = len(getattr(records[0], attr))
    return [round(mean(float(getattr(r, attr)[t]) for r in records), 3) for t in range(turns)]


def _distribution(values: list[int | None], turns: int) -> dict:
    counts = Counter(v if v is not None else "never" for v in values)
    hits = [v for v in values if v is not None]
    return {
        "by_turn": {str(t): counts.get(t, 0) / len(values) for t in range(0, turns + 1)},
        "never": counts.get("never", 0) / len(values),
        "median": median(hits) if hits else None,
        "mean": round(mean(hits), 2) if hits else None,
    }


def _seen_by_turn(records: list[GameRecord], getter, turns: int) -> list[float]:
    """P(seen by end of turn t) for t = 0 (opening hand) .. turns."""
    firsts = [getter(r) for r in records]
    return [round(sum(1 for f in firsts if f is not None and f <= t) / len(records), 4) for t in range(turns + 1)]


def aggregate(records: list[GameRecord], turns: int, key_cards: list[str]) -> dict:
    n = len(records)
    mana = _per_turn_mean(records, "mana")
    spent = _per_turn_mean(records, "spent")
    return {
        "games": n,
        "turns": turns,
        "mulligans": {
            "rate": sum(1 for r in records if r.mulligans) / n,
            "distribution": {str(k): v / n for k, v in sorted(Counter(r.mulligans for r in records).items())},
        },
        "per_turn": {
            "lands": _per_turn_mean(records, "lands"),
            "land_drop_pct": _per_turn_mean(records, "land_drop"),
            "mana_available": mana,
            "mana_spent": spent,
            "mana_unused": [round(a - s, 3) for a, s in zip(mana, spent)],
            "color_screw_pct": _per_turn_mean(records, "screwed"),
            "damage": _per_turn_mean(records, "damage"),
            "pod_damage": _per_turn_mean(records, "pod_damage"),
            "hand_size": _per_turn_mean(records, "hand"),
        },
        "commander_turn": _distribution([r.commander_turn for r in records], turns),
        "kill_turn_1opp": _distribution([r.kill1_turn for r in records], turns),
        "kill_turn_pod": _distribution([r.kill_pod_turn for r in records], turns),
        "key_cards": {
            name: _seen_by_turn(records, lambda r, name=name: r.first_seen.get(name), turns) for name in key_cards
        },
        "roles": {role: _seen_by_turn(records, lambda r, role=role: r.role_seen.get(role), turns) for role in ROLES},
        "shuffle": {
            "opening_lands_mean": round(mean(r.opening_lands for r in records), 3),
            "opening_lands_variance": round(pvariance([r.opening_lands for r in records]), 3),
            "opening_lands_distribution": {
                str(k): v / n for k, v in sorted(Counter(r.opening_lands for r in records).items())
            },
            "longest_land_run_mean": round(mean(r.longest_land_run for r in records), 3),
        },
    }
