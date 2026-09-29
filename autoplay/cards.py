"""Card model, decklist parsing, and Scryfall card data (cached locally)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

from .mana import Cost, parse_cost

SCRYFALL_COLLECTION = "https://api.scryfall.com/cards/collection"
CACHE_PATH = Path(os.environ.get("AUTOPLAY_CACHE", Path.home() / ".cache" / "autoplay")) / "cards.json"


@dataclass(eq=False)
class Card:
    name: str
    mana_cost: str = ""
    cmc: float = 0
    type_line: str = ""
    oracle: str = ""
    power: int = 0
    keywords: frozenset = frozenset()
    produced: frozenset = frozenset()
    is_commander: bool = False
    key: bool = False
    tags: dict[str, int] = field(default_factory=dict)
    mana_colors: frozenset = frozenset()  # what each mana unit this card makes can be spent as
    search_types: frozenset = frozenset()  # land subtypes a land-search may find ("basic" = any basic)
    cost: Cost = field(init=False)

    def __post_init__(self):
        self.cost = parse_cost(self.mana_cost)

    @property
    def is_land(self) -> bool:
        return "Land" in self.type_line

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.type_line

    @property
    def is_permanent(self) -> bool:
        return not ("Instant" in self.type_line or "Sorcery" in self.type_line)

    def copy(self) -> "Card":
        return replace(self, tags=dict(self.tags))

    def __repr__(self) -> str:
        return f"Card({self.name!r})"


def matches_search(card: Card, types: frozenset) -> bool:
    """Whether a land search for `types` ("basic", "land", or subtypes) can find `card`."""
    if not card.is_land:
        return False
    if "land" in types:
        return True
    if "basic" in types and "Basic" in card.type_line:
        return True
    return any(t in card.type_line for t in types if t not in ("basic", "land"))


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def card_from_scryfall(data: dict) -> Card:
    """Build a Card from Scryfall JSON. Multi-faced cards use the front face, except
    modal DFCs with a land face, which are treated as that land."""
    face = data
    faces = data.get("card_faces") or []
    if faces:
        face = faces[0]
        if data.get("layout") == "modal_dfc" and "Land" not in faces[0].get("type_line", ""):
            face = next((f for f in faces if "Land" in f.get("type_line", "")), faces[0])
        if face is not faces[0]:
            face = {**face, "mana_cost": ""}
    return Card(
        name=data["name"],
        mana_cost=face.get("mana_cost", data.get("mana_cost", "")),
        cmc=data.get("cmc", 0) if face is data or face is faces[0] else 0,
        type_line=face.get("type_line", data.get("type_line", "")),
        oracle=face.get("oracle_text", data.get("oracle_text", "")) or "",
        power=_int_or_zero(face.get("power", data.get("power"))),
        keywords=frozenset(data.get("keywords", [])),
        produced=frozenset(data.get("produced_mana", [])),
    )


# ---------------------------------------------------------------- decklists

_LINE_RE = re.compile(r"^(\d+)\s*x?\s+(.+?)\s*$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^(?://\s*)?([A-Za-z ]+?):?\s*(?:\(\d+\))?$")
_SKIP_SECTIONS = {"sideboard", "maybeboard", "considering", "tokens"}


@dataclass
class DeckEntry:
    name: str
    count: int
    commander: bool = False


def _clean_name(raw: str) -> tuple[str, bool]:
    commander = "*CMDR*" in raw or bool(re.search(r"\[[^\]]*commander", raw, re.IGNORECASE))
    name = re.sub(r"\[.*?\]|\^.*?\^|\*[A-Z]+\*", "", raw)
    name = re.sub(r"\s\([A-Za-z0-9]{2,6}\)\s*[\w-]*\s*$", "", name.strip())  # "(SET) 123"
    return name.strip(), commander


def parse_decklist(text: str) -> list[DeckEntry]:
    """Parse Moxfield / Archidekt / plain "1 Card Name" exports. Commanders come
    from a "Commander" section header, "*CMDR*", or an Archidekt [Commander] tag."""
    entries: list[DeckEntry] = []
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            sm = _SECTION_RE.match(line)
            if sm:
                section = sm.group(1).strip().lower()
            continue
        if section in _SKIP_SECTIONS:
            continue
        name, flagged = _clean_name(m.group(2))
        entries.append(DeckEntry(name, int(m.group(1)), flagged or section == "commander"))
    return entries


# ---------------------------------------------------------------- scryfall

def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _post_collection(names: list[str]) -> dict:
    body = json.dumps({"identifiers": [{"name": n} for n in names]}).encode()
    req = urllib.request.Request(
        SCRYFALL_COLLECTION,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "autoplay/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_card_data(names: list[str], cache_path: Path = CACHE_PATH, fetch=_post_collection) -> dict[str, dict]:
    """Return {lowercased name: scryfall json}, fetching missing cards 75 at a time."""
    cache = _load_cache(cache_path)
    missing = sorted({n for n in names if n.lower() not in cache})
    not_found: list[str] = []
    for i in range(0, len(missing), 75):
        result = fetch(missing[i : i + 75])
        for card in result.get("data", []):
            cache[card["name"].lower()] = card
            cache[card["name"].split(" // ")[0].lower()] = card
        not_found += [ident.get("name", "?") for ident in result.get("not_found", [])]
        time.sleep(0.1)  # Scryfall asks for 50-100ms between requests
    if missing:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    if not_found:
        raise LookupError(f"cards not found on Scryfall: {', '.join(not_found)}")
    return {n.lower(): cache[n.lower()] for n in names}
