"""Command line interface: `autoplay run`, `autoplay tags`, and `autoplay fetch`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .deck import deck_card_data, load_deck
from .overrides import load_overrides
from .shuffle import parse_routine
from .sim import PILOTS, simulate
from .tagger import ROLE_TAGS, is_untagged
from .tagger_api import TAGS_CACHE_PATH, cached_tags, fetch_tags

DEFAULT_SHUFFLE = "mash x3, riffle x2, cut"
DEFAULT_SEARCH_SHUFFLE = "mash x2, cut"


def _add_deck_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("deck", help="decklist text file (Moxfield / Archidekt export)")
    p.add_argument("--overrides", "-o", help="YAML overrides (key cards, tag fixes); defaults to <deck>.yaml if present")


def _overrides(args):
    ov_path = args.overrides
    if ov_path is None:
        guess = Path(args.deck).with_suffix(".yaml")
        ov_path = guess if guess.exists() else None
    return load_overrides(ov_path)


def _load(args):
    return load_deck(args.deck, _overrides(args))


def cmd_run(args) -> int:
    parse_routine(args.shuffle)  # fail fast on typos
    parse_routine(args.search_shuffle)
    deck = _load(args)
    result = simulate(
        deck, n=args.games, turns=args.turns, shuffle=args.shuffle, search_shuffle=args.search_shuffle, seed=args.seed,
        baseline=not args.no_baseline, draw_first_turn=not args.skip_first_draw, pilot=args.pilot,
    )
    _print_summary(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1))
        print(f"\nJSON written to {args.json}")
    if args.out:
        from .report import write_report

        path = write_report(result, args.out)
        print(f"Report written to {path}")
    return 0


def _print_summary(r: dict) -> None:
    h, b = r["human"], r.get("random")
    d = r["deck"]
    print(f"{d['name']}: {' + '.join(d['commanders'])}  ({d['size']} cards, {d['lands']} lands)")
    print(f"{r['settings']['games']} games x {r['settings']['turns']} turns, shuffle: {r['settings']['shuffle']}, "
          f"search shuffle: {r['settings']['search_shuffle']}\n")

    def row(label, hv, bv=None):
        print(f"  {label:<34}{hv:>10}" + (f"{bv:>12}" if bv is not None else ""))

    row("", "human", "random" if b else None)
    pct = lambda x: f"{x:.0%}"
    turn = lambda x: "-" if x is None else f"T{x:g}"
    row("Mulligan rate", pct(h["mulligans"]["rate"]), b and pct(b["mulligans"]["rate"]))
    row("Commander cast (median)", turn(h["commander_turn"]["median"]), b and turn(b["commander_turn"]["median"]))
    row("Kill 1 opponent (median)", turn(h["kill_turn_1opp"]["median"]), b and turn(b["kill_turn_1opp"]["median"]))
    row("Kill 3 opponents (median)", turn(h["kill_turn_pod"]["median"]), b and turn(b["kill_turn_pod"]["median"]))
    row("Opening-hand lands variance", f"{h['shuffle']['opening_lands_variance']:.2f}", b and f"{b['shuffle']['opening_lands_variance']:.2f}")

    print("\n  turn   lands  drop%  mana  spent  screw%  damage")
    pt = h["per_turn"]
    for t in range(r["settings"]["turns"]):
        print(
            f"  {t + 1:>4}  {pt['lands'][t]:>6.2f}  {pt['land_drop_pct'][t]:>5.0%}  {pt['mana_available'][t]:>4.1f}"
            f"  {pt['mana_spent'][t]:>5.1f}  {pt['color_screw_pct'][t]:>6.0%}  {pt['damage'][t]:>6.1f}"
        )
    if d["off_identity"]:
        print(f"\n  WARNING: outside {' + '.join(d['commanders'])}'s color identity: {', '.join(d['off_identity'])}")
    if d["untagged"]:
        print(f"\n  {len(d['untagged'])} cards with unmodeled text (played as vanilla): {', '.join(d['untagged'])}")
    if d["scryfall_tags"]["missing"]:
        print(f"\n  {len(d['scryfall_tags']['missing'])} cards have no Scryfall Tagger tags cached; "
              "run `autoplay fetch` on this deck to add them to the report")


def cmd_tags(args) -> int:
    deck = _load(args)
    seen = set()
    for card in deck.commanders + deck.library:
        if card.name in seen:
            continue
        seen.add(card.name)
        effects = {k: v for k, v in card.tags.items() if k not in ROLE_TAGS}
        roles = sorted(k for k in card.tags if k in ROLE_TAGS)
        tag_str = ", ".join(f"{k}:{v}" if v != 1 else k for k, v in effects.items())
        flag = " [UNMODELED]" if is_untagged(card) else ""
        key = " [KEY]" if card.key else ""
        cmd = " [COMMANDER]" if card.is_commander else ""
        colors = "".join(sorted(card.mana_colors)) if card.tags.get("mana") or card.tags.get("ritual") else ""
        print(f"{card.name:<40} {tag_str}{' mana=' + colors if colors else ''}  ({', '.join(roles)}){cmd}{key}{flag}")
        if card.name in deck.scryfall_tags:
            print(f"{'':<40} scryfall: {', '.join(deck.scryfall_tags[card.name]['tags']) or '-'}")
    return 0


def cmd_fetch(args) -> int:
    _, data = deck_card_data(args.deck, _overrides(args))
    have = cached_tags(data)
    todo = len({d["name"] for d in data.values()}) - (0 if args.refresh else len(have))
    if todo:
        print(f"Fetching Scryfall Tagger tags for {todo} cards, {args.delay:g}s apart (~{todo * args.delay / 60:.0f} min)")
    counter = iter(range(1, todo + 1))
    tags = fetch_tags(
        data, delay=args.delay, refresh=args.refresh,
        progress=lambda name, status: print(f"  [{next(counter, todo)}/{todo}] {name}: {status}", flush=True),
    )
    missing = sorted({d["name"] for d in data.values()} - tags.keys())
    print(f"Card data and tags for {len(tags)} cards cached in {TAGS_CACHE_PATH.parent}")
    if missing:
        print(f"No tags for: {', '.join(missing)} (run fetch again to retry)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoplay", description="Goldfish playtest simulator for Commander decks")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="simulate games and report stats")
    _add_deck_args(run)
    run.add_argument("-n", "--games", type=int, default=1000)
    run.add_argument("-t", "--turns", type=int, default=10)
    run.add_argument("-s", "--shuffle", default=DEFAULT_SHUFFLE,
                     help=f'shuffle routine, e.g. "pile7, riffle x4, mash x2, cut" (default: "{DEFAULT_SHUFFLE}")')
    run.add_argument("--search-shuffle", default=DEFAULT_SEARCH_SHUFFLE,
                     help=f'shuffle routine after a library search (tutors, fetches) (default: "{DEFAULT_SEARCH_SHUFFLE}")')
    run.add_argument("--seed", type=int)
    run.add_argument("--pilot", choices=sorted(PILOTS), default="greedy",
                     help="play strategy; 'landfall' casts landfall cards before the turn's land drop")
    run.add_argument("--no-baseline", action="store_true", help="skip the perfectly-random comparison run")
    run.add_argument("--skip-first-draw", action="store_true", help="skip the turn-1 draw (1v1 rules)")
    run.add_argument("--out", default="report.html", help="HTML report path ('' to skip)")
    run.add_argument("--json", help="also write raw results as JSON")
    run.set_defaults(func=cmd_run)

    tags = sub.add_parser("tags", help="show how each card was tagged")
    _add_deck_args(tags)
    tags.set_defaults(func=cmd_tags)

    fetch = sub.add_parser("fetch", help="cache Scryfall card data and Tagger tags for a deck (slow, polite)")
    _add_deck_args(fetch)
    fetch.add_argument("--delay", type=float, default=3.0, help="seconds between Tagger requests (default: 3)")
    fetch.add_argument("--refresh", action="store_true", help="re-fetch tags that are already cached")
    fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
