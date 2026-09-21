"""Polite, cached HTTP for the ingestion pipeline.

Every response is cached on disk keyed by a hash of the request, so a second
run of the pipeline is fully offline and byte-for-byte repeatable - which is
what makes the pipeline idempotent and its output reviewable. `refresh=True`
bypasses the cache for that call.

Only the lawful, attributable sources named in ADR-026 are contacted:
OpenStreetMap (Overpass), Wikidata and Wikipedia.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.paths import artifacts_dir

USER_AGENT = ("NavigIQ-ingest/2.0 (Bengaluru exploration companion; "
              "https://github.com/navigiq; data use under ODbL / CC BY-SA)")

ALLOWED_HOSTS = (
    "overpass-api.de", "lz4.overpass-api.de", "z.overpass-api.de",
    "overpass.kumi.systems", "www.wikidata.org", "query.wikidata.org",
    "en.wikipedia.org", "commons.wikimedia.org",
)


class FetchError(RuntimeError):
    pass


def _cache_path(namespace: str, key: str) -> Path:
    d = artifacts_dir() / "raw" / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def request_key(method: str, url: str, params: dict | None, data: dict | None) -> str:
    blob = json.dumps({"m": method, "u": url, "p": params, "d": data}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class CachedClient:
    def __init__(self, namespace: str, *, min_interval_s: float = 1.0,
                 timeout_s: float = 180.0, retries: int = 4, refresh: bool = False) -> None:
        self.namespace = namespace
        self.min_interval_s = min_interval_s
        self.retries = retries
        self.refresh = refresh
        self._last = 0.0
        self._client = httpx.Client(timeout=timeout_s, headers={"User-Agent": USER_AGENT},
                                    follow_redirects=True)
        self.network_calls = 0
        self.cache_hits = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CachedClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch_json(self, url: str, *, method: str = "GET", params: dict | None = None,
                   data: dict | None = None, cache_as: str | None = None) -> Any:
        """`cache_as` replaces the URL in the cache key - mirrors of one
        service (Overpass) return the same data for the same query."""
        host = httpx.URL(url).host
        if host not in ALLOWED_HOSTS:
            raise FetchError(f"host not allowed for ingestion: {host}")
        key = request_key(method, cache_as or url, params, data)
        legacy = _cache_path(self.namespace, request_key(method, url, params, data))
        if cache_as and legacy.exists() and not _cache_path(self.namespace, key).exists():
            legacy.rename(_cache_path(self.namespace, key))
        path = _cache_path(self.namespace, key)
        if path.exists() and not self.refresh:
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["body"]

        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                self._last = time.monotonic()
                self.network_calls += 1
                resp = self._client.request(method, url, params=params, data=data)
                if resp.status_code in (429, 502, 503, 504):
                    raise FetchError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                body = resp.json()
                path.write_text(json.dumps({
                    "url": url, "params": params, "data": data,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "body": body,
                }, ensure_ascii=False), encoding="utf-8")
                return body
            except (httpx.HTTPError, FetchError, ValueError) as exc:
                last_exc = exc
                time.sleep(min(60.0, 5.0 * (2 ** attempt)))
        raise FetchError(f"{url}: {last_exc}")
