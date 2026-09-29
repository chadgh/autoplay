# Autoplay: MTG Commander Deck Goldfish Simulator

## Context
The user wants a tool that auto-playtests their Commander decks: simulate human-style shuffling, play X turns
(draw, play lands/spells, attack) with no opponent, repeat N times, and aggregate stats. Goals (all four chosen):
mana/curve health, card access, goldfish speed, and shuffle realism (human shuffles vs true random).
Interface now: Python CLI + HTML report; later a web app — so the engine is a standalone library emitting JSON.
Project dir `/home/chadgh/src/sandbox/autoplaytest` is empty (greenfield, not a git repo).

## Decisions (agreed)
- Pure Python 3.12+, `uv` for project mgmt, pytest.
- Card effects: Scryfall bulk data (cached) + auto-tagging from oracle text + per-deck `overrides.yaml`.
- Pre-shuffle order chains from the previous game (zones gathered in configurable order).
- Greedy heuristic pilot behind an interface.
- Unrecognized cards played as vanilla and listed as "untagged" in the report.

## Layout
```
pyproject.toml            # deps: httpx, pyyaml, jinja2, plotly(js via CDN), typer; dev: pytest
autoplay/
  cards.py      # Card dataclass, decklist parser (Moxfield/Archidekt text, "*CMDR*" / "Commander" section), Scryfall bulk cache (~/.cache/autoplay)
  tagger.py     # oracle-text regex rules -> tags: land, mana_rock, mana_dork, ramp_land, draw:N, creature, haste, burn:N, drain:N, tutor; produces mana ability (amount, colors)
  overrides.py  # load overrides.yaml: add/replace tags, mark key cards
  shuffle.py    # riffle (GSR model), mash, overhand, pile(n), random; parse routine string "pile7, riffle x4, mash x2"
  game.py       # GameState zones (library, hand, battlefield, graveyard, command); turn loop: untap, draw (skip T1), main, combat; commander tax; gather_for_next_game(order)
  mana.py       # color-aware payment solver (sources -> cost incl. generic/hybrid basics)
  pilot.py      # Pilot protocol: mulligan(hand) (London + free first mulligan), choose_plays(state); GreedyPilot
  stats.py      # per-turn event recorder -> aggregate JSON (percentiles, per-turn series)
  sim.py        # run(deck, n, turns, shuffle, seed, pilot) -> Result (JSON-serializable); also runs random-baseline comparison
  report.py     # Jinja2 HTML template + Plotly charts
  cli.py        # `autoplay run deck.txt -n 5000 -t 10 --shuffle "..." --seed 1 --overrides o.yaml --out report.html`; `autoplay tags deck.txt` to inspect tagging
tests/          # per-module tests
docs/superpowers/specs/2026-09-29-autoplay-design.md  # spec (copy of design section below)
```

## Stats (per turn, aggregated)
- Mana: land-drop hit %, mana available vs spent, unused mana, color-screw (castable-by-amount but not by colors), mulligan rate/count.
- Commander: first-cast-turn distribution.
- Card access: P(key card seen by turn T); first-seen turn per tag role.
- Goldfish: cumulative damage by turn; kill turn distribution vs 1 and 3 opponents at 40 life; commander damage (21) tracked.
- Shuffle realism: land clumping (longest land run in top 20, land-count variance in opening 7) human vs random; headline stats side-by-side vs random baseline.

## Greedy pilot rules (v1)
1. Mulligan: keep 7 with 2–5 lands (configurable); London mulligan, bottom highest-cmc excess / lands if flooded.
2. Land drop: prefer land producing a missing color needed in hand.
3. Cast ramp (rocks, dorks, ramp_land) first, then draw, then commander if castable, then maximize mana spent (highest cmc first, fill remainder).
4. Combat: attack with all non-summoning-sick creatures (or haste); burn/drain applied to damage total on resolution.

## Implementation order (TDD per module)
1. `git init`, uv project scaffold, write spec doc, commit.
2. `shuffle.py` + statistical tests (riffle×7 ≈ uniform position distribution; mash/pile deterministic with seed).
3. `cards.py` (parser + Scryfall bulk download/cache; tests with a small fixture JSON, no network).
4. `tagger.py` + golden tests (Sol Ring, Llanowar Elves, Cultivate, Rampant Growth, Harmonize, Lightning Bolt, Blood Artist-style drain, Command Tower, fetch/dual lands).
5. `mana.py` payment solver + tests.
6. `game.py` + `pilot.py` with scripted-library tests (known order → expected plays/damage).
7. `stats.py` + `sim.py` (chaining, baseline comparison, seeding).
8. `cli.py` + `report.py`.
9. Real-deck smoke run.

## Verification
- `uv run pytest` all green.
- `uv run autoplay tags sample_deck.txt` shows sensible tags; untagged list reviewed.
- `uv run autoplay run sample_deck.txt -n 2000 -t 10 --seed 1` completes in reasonable time (<~30s), prints summary, writes report.html; open it and sanity-check: ~land-drop % near hypergeometric expectation for random baseline; riffle×7 stats ≈ random; riffle×1 shows clumping.
