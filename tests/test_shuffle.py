import random
from statistics import mean

import pytest

from autoplay.shuffle import parse_routine, riffle, mash, overhand, pile, cut, run_routine


def deck(n=99):
    return list(range(n))


@pytest.mark.parametrize("fn", [riffle, mash, overhand, cut, lambda d, r: pile(d, r, 7)])
def test_shuffles_are_permutations(fn):
    rng = random.Random(1)
    out = fn(deck(), rng)
    assert sorted(out) == deck()


def test_pile_is_deterministic():
    a = pile(deck(), random.Random(1), 7)
    b = pile(deck(), random.Random(2), 7)
    assert a == b
    assert a != deck()


def test_single_riffle_preserves_rising_sequences():
    # One riffle of a sorted deck interleaves two increasing runs -> at most 2 rising sequences.
    out = riffle(deck(), random.Random(3))
    positions = {card: i for i, card in enumerate(out)}
    rising = 1 + sum(1 for c in range(1, 99) if positions[c] < positions[c - 1])
    assert rising <= 2


def _top_card_mean(routine, trials=3000):
    rng = random.Random(42)
    steps = parse_routine(routine)
    return mean(run_routine(deck(), steps, rng)[0] for _ in range(trials))


def test_many_riffles_approach_uniform():
    # Uniform top card from 0..98 has mean 49.
    assert abs(_top_card_mean("riffle x8") - 49) < 3


def test_one_riffle_is_far_from_uniform():
    assert abs(_top_card_mean("riffle") - 49) > 10


def test_parse_routine():
    steps = parse_routine("pile7, riffle x4, mash x2, cut")
    assert [(s.name, s.param) for s in steps] == (
        [("pile", 7)] + [("riffle", None)] * 4 + [("mash", None)] * 2 + [("cut", None)]
    )


def test_parse_routine_rejects_unknown():
    with pytest.raises(ValueError):
        parse_routine("smoosh")
