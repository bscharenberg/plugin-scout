"""Catalog loader: fetch, cache and diff the public Hermes plugin catalog.

Pure Python (standard library only) so it can be tested without Hermes.
The only network call is a GET of the public catalog index published by
Nous Research. Everything else works from the local cache.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from . import sanitize
except ImportError:  # loaded as a plain module (tests)
    import sanitize

CATALOG_URL = "https://hermes-agent.nousresearch.com/docs/api/plugin-catalog.json"
CACHE_TTL_SECONDS = 6 * 60 * 60          # same window Hermes uses for its own copy
MAX_BYTES = 20 * 1024 * 1024             # refuse anything absurdly large
MAX_ENTRIES = 20000                      # the catalog has about 2,100 today
RETRY_AFTER_SECONDS = 600                # after a failed download, use the cached copy for 10 minutes
_FAILED_UNTIL: dict[str, float] = {}     # cache path -> time before which we don't try again
USER_AGENT = "plugin-scout-hermes-plugin"

# Fields kept in a weekly snapshot. Small enough to keep many weeks in state.
SNAPSHOT_FIELDS = ("sha", "version", "category", "tier")


class CatalogError(RuntimeError):
    """The catalog could not be loaded from the network or the cache."""


ALLOWED_PREFIX = "https://hermes-agent.nousresearch.com/"
# The catalog's official addresses: the docs site, and the Nous GitHub Pages site it redirects to.
ALLOWED_PREFIXES = (ALLOWED_PREFIX, "https://nousresearch.github.io/hermes-agent/")


def _allowed(url: str) -> bool:
    return str(url).startswith(ALLOWED_PREFIXES)


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it stays on the catalog's own HTTPS host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise CatalogError("plugin catalog redirected to another address; refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_catalog(url: str = CATALOG_URL, timeout: float = 30.0) -> dict[str, Any]:
    """Download the catalog index and check its shape. Raises CatalogError."""
    if not _allowed(url):
        raise CatalogError("plugin catalog address must be the official HTTPS catalog")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_SameHostRedirects())  # default TLS checks stay on
    try:
        with opener.open(req, timeout=timeout) as resp:
            if not _allowed(resp.geturl()):
                raise CatalogError("plugin catalog answered from another address; refused")
            raw = resp.read(MAX_BYTES + 1)
    except CatalogError:
        raise
    except Exception as exc:  # network, DNS, TLS, timeout
        raise CatalogError("could not reach the plugin catalog") from exc
    if len(raw) > MAX_BYTES:
        raise CatalogError("plugin catalog payload is unexpectedly large")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as exc:
        raise CatalogError("plugin catalog is not valid JSON") from exc
    return validate(data)


def validate(data: Any) -> dict[str, Any]:
    """Accept only the documented shape: {"entries": [...], "removed": [...]}."""
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise CatalogError("plugin catalog has an unexpected shape")
    # Catalog text is written by third parties: keep only valid names and clean every field.
    entries = [e for e in map(sanitize.catalog_entry, data["entries"][:MAX_ENTRIES]) if e]
    raw_removed = data.get("removed") if isinstance(data.get("removed"), list) else []
    removed = [r for r in map(sanitize.removed_entry, raw_removed[:MAX_ENTRIES]) if r]
    return {"generated_at": sanitize.clean(data.get("generated_at"), 40), "entries": entries,
            "removed": removed}


class CatalogStore:
    """Catalog with a file cache. Falls back to a stale cache when offline."""

    def __init__(
        self,
        cache_dir: Path,
        fetcher: Callable[[], dict[str, Any]] = fetch_catalog,
        clock: Callable[[], float] = time.time,
        ttl: float = CACHE_TTL_SECONDS,
    ):
        self.cache_path = Path(cache_dir) / "catalog.json"
        self._fetch = fetcher
        self._now = clock
        self._ttl = ttl

    def _read_cache(self) -> Optional[dict[str, Any]]:
        try:
            blob = json.loads(self.cache_path.read_text(encoding="utf-8"))
            fetched_at = float(blob["fetched_at"])
            if not (0 < fetched_at <= self._now() + 60):  # a time in the future would look fresh forever
                return None
            return {"fetched_at": fetched_at, "catalog": validate(blob["catalog"])}
        except Exception:
            return None

    def _write_cache(self, catalog: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")  # no shared temp name
        tmp.write_text(json.dumps({"fetched_at": self._now(), "catalog": catalog}), encoding="utf-8")
        tmp.replace(self.cache_path)  # atomic on the same filesystem

    def load(self, force: bool = False) -> dict[str, Any]:
        """Return {"catalog", "fetched_at", "source", "stale"}.

        source is "cache" or "network". stale is True when the network failed
        and an older cache was used instead. Raises CatalogError only when
        there is neither network nor cache.
        """
        cached = self._read_cache()
        if cached and not force and self._now() - cached["fetched_at"] < self._ttl:
            return {**cached, "source": "cache", "stale": False}
        key = str(self.cache_path)
        if not force and self._now() < _FAILED_UNTIL.get(key, 0):  # offline recently: don't wait again
            if cached:
                return {**cached, "source": "cache", "stale": True}
            raise CatalogError("could not reach the plugin catalog")
        try:
            catalog = self._fetch()
        except CatalogError:
            _FAILED_UNTIL[key] = self._now() + RETRY_AFTER_SECONDS
            if cached:
                return {**cached, "source": "cache", "stale": True}
            raise
        _FAILED_UNTIL.pop(key, None)
        self._write_cache(catalog)
        return {"catalog": catalog, "fetched_at": self._now(), "source": "network", "stale": False}


def index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Entries keyed by catalog name."""
    return {e["name"]: e for e in catalog.get("entries", [])}


def snapshot(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Slim per-entry record used to compare one week with the next."""
    return {
        e["name"]: {k: e.get(k) for k in SNAPSHOT_FIELDS}
        for e in catalog.get("entries", [])
    }


def diff(old: dict[str, dict[str, Any]], new_catalog: dict[str, Any]) -> dict[str, list]:
    """What changed between an earlier snapshot and the current catalog.

    new: names present now but not before.
    updated: names whose pinned sha changed (with old and new version).
    removed: names that left the catalog, with the reason Nous recorded if any.
    """
    current = snapshot(new_catalog)
    reasons = {r["name"]: r.get("reason", "") for r in new_catalog.get("removed", [])}
    new = sorted(n for n in current if n not in old)
    updated = sorted(
        (
            {"name": n, "from": old[n].get("version"), "to": current[n].get("version")}
            for n in current
            if n in old and old[n].get("sha") != current[n].get("sha")
        ),
        key=lambda u: u["name"],
    )
    removed = sorted(
        ({"name": n, "reason": reasons.get(n, "")} for n in old if n not in current),
        key=lambda r: r["name"],
    )
    return {"new": new, "updated": updated, "removed": removed}
