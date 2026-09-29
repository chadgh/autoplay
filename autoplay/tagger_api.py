"""Community card tags from Scryfall Tagger (tagger.scryfall.com), cached locally.

Tagger has no public API; this uses the GraphQL endpoint its web page calls, which needs
the page's session cookie and CSRF token. It's unsupported and may change or block us,
so `autoplay fetch` pulls tags slowly into the cache ahead of time and `autoplay run`
only reads the cache.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .cards import CACHE_PATH, _load_cache

TAGGER = "https://tagger.scryfall.com"
TAGS_CACHE_PATH = CACHE_PATH.parent / "tags.json"
USER_AGENT = "autoplay/0.1"

_CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')
_QUERY = """query($set: String!, $number: String!) {
  card: cardBySet(set: $set, number: $number, back: false) {
    name
    taggings { status tag { name type ancestorTags { name } } }
    relationships { classifier name relatedName }
  }
}"""


class TaggerClient:
    """Looks up one printing at a time. Returns {"tags": [...], "relationships": [...]}."""

    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf: str | None = None

    def _open(self, req, timeout=30):
        req.add_header("User-Agent", USER_AGENT)
        return self.opener.open(req, timeout=timeout)

    def _session(self, set_code: str, number: str) -> str:
        url = f"{TAGGER}/card/{set_code}/{urllib.parse.quote(number)}"
        with self._open(urllib.request.Request(url)) as resp:
            m = _CSRF_RE.search(resp.read().decode("utf-8", "replace"))
        if not m:
            raise RuntimeError("no CSRF token on the Tagger page; the site may have changed")
        return m.group(1)

    def __call__(self, set_code: str, number: str) -> dict:
        if self.csrf is None:
            self.csrf = self._session(set_code, number)
        body = json.dumps({"query": _QUERY, "variables": {"set": set_code, "number": number}}).encode()
        req = urllib.request.Request(
            f"{TAGGER}/graphql", data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": self.csrf},
        )
        with self._open(req) as resp:
            payload = json.load(resp)
        if payload.get("errors"):
            raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
        return parse_card(payload["data"]["card"] or {})


def parse_card(card: dict) -> dict:
    """Keep gameplay (oracle) tags plus their parent tags, and card-to-card relationships."""
    tags: set[str] = set()
    for tagging in card.get("taggings") or []:
        tag = tagging.get("tag") or {}
        if tag.get("type") != "ORACLE_CARD_TAG" or "REJECT" in (tagging.get("status") or ""):
            continue
        tags.add(tag["name"])
        tags.update(a["name"] for a in tag.get("ancestorTags") or [])
    rels = [
        {"kind": r["classifier"], "a": r["name"], "b": r["relatedName"]}
        for r in card.get("relationships") or []
        if r.get("classifier") and r.get("name") and r.get("relatedName")
    ]
    return {"tags": sorted(tags), "relationships": rels}


def _key(card_json: dict) -> str:
    return card_json.get("oracle_id") or (card_json.get("card_faces") or [{}])[0].get("oracle_id") or card_json["name"]


def cached_tags(card_data: dict[str, dict], cache_path: Path = TAGS_CACHE_PATH) -> dict[str, dict]:
    """{card name: {"tags", "relationships"}} for cards already in the cache. No network."""
    cache = _load_cache(cache_path)
    out = {}
    for data in card_data.values():
        hit = cache.get(_key(data))
        if hit is not None:
            out[data["name"]] = hit
    return out


def fetch_tags(
    card_data: dict[str, dict],
    cache_path: Path = TAGS_CACHE_PATH,
    fetch: Callable[[str, str], dict] | None = None,
    delay: float = 3.0,
    refresh: bool = False,
    progress: Callable[[str, str], None] = lambda name, status: None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, dict]:
    """Fetch Tagger data for cards not yet cached, waiting `delay` seconds between requests.

    Tags belong to the card (oracle), so each card is looked up once, by the printing
    Scryfall returned. The cache is saved after every card, so an interrupted fetch keeps
    its progress. Per-card failures are reported through `progress` and skipped; an HTTP
    429 or 403 stops the fetch, since that means we're being throttled or blocked.
    """
    fetch = fetch or TaggerClient()
    cache = _load_cache(cache_path)
    todo = {}
    for data in card_data.values():
        if refresh or _key(data) not in cache:
            todo.setdefault(_key(data), data)
    first = True
    for key, data in sorted(todo.items(), key=lambda kv: kv[1]["name"]):
        if not first:
            sleep(delay)
        first = False
        try:
            cache[key] = fetch(data["set"], data["collector_number"])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                progress(data["name"], f"stopped: Tagger returned HTTP {e.code}; try again later with a longer --delay")
                break
            progress(data["name"], f"failed: HTTP {e.code}")
            continue
        except (OSError, RuntimeError, KeyError, ValueError) as e:
            progress(data["name"], f"failed: {e}")
            continue
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
        progress(data["name"], f"{len(cache[key]['tags'])} tags")
    return cached_tags(card_data, cache_path)
