"""Human-style shuffle models. Decks are lists with index 0 as the top card."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable, Sequence

Deck = list


def _binomial_cut(n: int, rng: random.Random) -> int:
    return sum(1 for _ in range(n) if rng.random() < 0.5)


def riffle(deck: Sequence, rng: random.Random) -> Deck:
    """Gilbert-Shannon-Reeds riffle: binomial cut, then drop from each packet with
    probability proportional to its remaining size."""
    k = _binomial_cut(len(deck), rng)
    left, right = list(deck[:k]), list(deck[k:])
    out: Deck = []
    i = j = 0
    while i < len(left) or j < len(right):
        rem_l, rem_r = len(left) - i, len(right) - j
        if rng.random() * (rem_l + rem_r) < rem_l:
            out.append(left[i])
            i += 1
        else:
            out.append(right[j])
            j += 1
    return out


def mash(deck: Sequence, rng: random.Random) -> Deck:
    """Mash shuffle: split near the middle and push halves together in clumps."""
    k = _binomial_cut(len(deck), rng)
    packets = [list(deck[:k]), list(deck[k:])]
    idx = [0, 0]
    out: Deck = []
    turn = rng.randrange(2)
    while idx[0] < len(packets[0]) or idx[1] < len(packets[1]):
        if idx[turn] >= len(packets[turn]):
            turn = 1 - turn
        clump = 1
        while rng.random() < 0.4:  # geometric clump size, mean ~1.7
            clump += 1
        take = packets[turn][idx[turn] : idx[turn] + clump]
        out.extend(take)
        idx[turn] += len(take)
        turn = 1 - turn
    return out


def overhand(deck: Sequence, rng: random.Random) -> Deck:
    """Overhand shuffle: peel chunks off the top onto a new pile (reversing chunk order)."""
    remaining = list(deck)
    out: Deck = []
    mean_chunk = max(1, len(deck) // 8)
    while remaining:
        size = max(1, min(len(remaining), round(rng.gauss(mean_chunk, mean_chunk / 2))))
        chunk, remaining = remaining[:size], remaining[size:]
        out = chunk + out
    return out


def pile(deck: Sequence, rng: random.Random, piles: int = 7) -> Deck:
    """Pile 'shuffle': deal round-robin into piles, then stack piles in order. Deterministic."""
    stacks: list[Deck] = [[] for _ in range(piles)]
    for i, card in enumerate(deck):
        stacks[i % piles].insert(0, card)
    return [card for stack in stacks for card in stack]


def cut(deck: Sequence, rng: random.Random) -> Deck:
    """Single cut near the middle."""
    k = _binomial_cut(len(deck), rng)
    return list(deck[k:]) + list(deck[:k])


def uniform(deck: Sequence, rng: random.Random) -> Deck:
    out = list(deck)
    rng.shuffle(out)
    return out


SHUFFLES: dict[str, Callable] = {
    "riffle": riffle,
    "mash": mash,
    "overhand": overhand,
    "pile": pile,
    "cut": cut,
    "random": uniform,
}


@dataclass(frozen=True)
class Step:
    name: str
    param: int | None = None


_STEP_RE = re.compile(r"^([a-z]+)(\d+)?(?:\s*x\s*(\d+))?$")


def parse_routine(routine: str) -> list[Step]:
    """Parse e.g. "pile7, riffle x4, mash x2, cut" into a list of steps."""
    steps: list[Step] = []
    for token in routine.split(","):
        token = token.strip().lower()
        if not token:
            continue
        m = _STEP_RE.match(token)
        if not m or m.group(1) not in SHUFFLES:
            raise ValueError(f"unknown shuffle step: {token!r} (known: {', '.join(SHUFFLES)})")
        name, param, reps = m.group(1), m.group(2), m.group(3)
        steps.extend([Step(name, int(param) if param else None)] * int(reps or 1))
    return steps


def run_routine(deck: Sequence, steps: list[Step], rng: random.Random) -> Deck:
    out = list(deck)
    for step in steps:
        fn = SHUFFLES[step.name]
        out = fn(out, rng, step.param) if step.param is not None else fn(out, rng)
    return out
