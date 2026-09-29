from autoplay.mana import Cost, color_screwed, parse_cost, solve_payment

G, U, C = frozenset("G"), frozenset("U"), frozenset("C")
ANY = frozenset("WUBRG")


def test_parse_cost():
    assert parse_cost("{2}{G}{G}") == Cost(2, (G, G))
    assert parse_cost("{X}{R}") == Cost(0, (frozenset("R"),))
    assert parse_cost("{G/U}") == Cost(0, (frozenset("GU"),))
    assert parse_cost("{G/P}{1}") == Cost(1, ())
    assert parse_cost("") == Cost()


def test_pays_simple():
    assert sorted(solve_payment(parse_cost("{1}{G}"), [G, C])) == [0, 1]


def test_insufficient_colors():
    assert solve_payment(parse_cost("{G}{G}"), [G, U, U]) is None
    assert color_screwed(parse_cost("{G}{G}"), [G, U, U])


def test_uses_rainbow_only_when_needed():
    # {U}{G}: G must come from Forest, U from rainbow; generic from Sol Ring units.
    pool = [ANY, G, C, C]
    used = solve_payment(parse_cost("{2}{U}{G}"), pool)
    assert sorted(used) == [0, 1, 2, 3]
    used = solve_payment(parse_cost("{1}{G}"), pool)
    assert 0 not in used  # rainbow preserved


def test_matching_requires_augmenting():
    # Greedy would give ANY to G and fail U; matching must reassign.
    pool = [ANY, G]
    assert solve_payment(parse_cost("{U}{G}"), pool) is not None


def test_colorless_pip_needs_true_colorless():
    assert solve_payment(parse_cost("{C}"), [ANY]) is None
    assert solve_payment(parse_cost("{C}"), [C]) == [0]
