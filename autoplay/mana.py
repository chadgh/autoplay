"""Mana costs and a color-aware payment solver.

A mana pool is a list of units; each unit is a frozenset of the symbols it can be
spent as (e.g. {"G"} for a Forest, {"W","U","B","R","G"} for Command Tower,
{"C"} for Sol Ring). Generic costs can be paid by any unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COLORS = "WUBRG"
_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class Cost:
    generic: int = 0
    pips: tuple[frozenset, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.generic + len(self.pips)

    def plus(self, generic: int) -> "Cost":
        return Cost(self.generic + generic, self.pips)


def parse_cost(mana_cost: str) -> Cost:
    """Parse Scryfall mana_cost like "{2}{G}{G}". X costs count as 0, Phyrexian
    pips are assumed paid with life, hybrid pips accept either color, {2/W}
    is treated as its colored half."""
    generic = 0
    pips: list[frozenset] = []
    for sym in _SYMBOL_RE.findall(mana_cost or ""):
        if sym.isdigit():
            generic += int(sym)
        elif sym in ("X", "Y", "Z"):
            continue
        elif sym == "S":
            generic += 1
        elif "/P" in sym:
            continue
        elif "/" in sym:
            parts = [p for p in sym.split("/") if p in COLORS or p == "C"]
            if parts:
                pips.append(frozenset(parts))
            else:
                generic += 1
        elif sym in COLORS or sym == "C":
            pips.append(frozenset(sym))
    return Cost(generic, tuple(pips))


def solve_payment(cost: Cost, pool: list[frozenset]) -> list[int] | None:
    """Return indices of pool units that pay `cost`, or None if unpayable.
    Prefers spending the least flexible units so rainbow mana is kept."""
    if cost.total > len(pool):
        return None
    order = sorted(range(len(pool)), key=lambda i: len(pool[i]))
    match: dict[int, int] = {}  # unit index -> pip index

    def try_assign(p: int, seen: set[int]) -> bool:
        for u in order:
            if u in seen or not (pool[u] & cost.pips[p]):
                continue
            seen.add(u)
            if u not in match or try_assign(match[u], seen):
                match[u] = p
                return True
        return False

    pip_order = sorted(range(len(cost.pips)), key=lambda p: len(cost.pips[p]))
    for p in pip_order:
        if not try_assign(p, set()):
            return None
    free = [u for u in order if u not in match]
    if len(free) < cost.generic:
        return None
    return list(match) + free[: cost.generic]


def color_screwed(cost: Cost, pool: list[frozenset]) -> bool:
    """True when the pool is big enough but lacks the right colors."""
    return cost.total <= len(pool) and solve_payment(cost, pool) is None
