"""Thin ESI client: compatibility-date header, ETag caching, rate-limit awareness."""

import hashlib
import json
import logging
import time
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

ETAG_TTL = 7 * 24 * 3600
BREAKER_KEY = "esi:breaker"
BREAKER_SECONDS = 300


class EsiError(Exception):
    pass


class EsiRateLimited(EsiError):
    def __init__(self, retry_after: int):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class EsiUnavailable(EsiError):
    pass


def _cache_key(
    method: str, path: str, params: dict | None, body: Any, character_id: int | None
) -> str:
    # The character is part of the key: an authenticated response must never be served from
    # another character's cache entry.
    raw = json.dumps([method, path, params or {}, body, character_id], sort_keys=True, default=str)
    return "esi:etag:" + hashlib.sha1(raw.encode()).hexdigest()


def _wait_seconds(resp: httpx.Response) -> int:
    """How long ESI asks us to wait: `Retry-After` on 429, the error-limit reset on 420.
    A missing or non-numeric value (Retry-After may be an HTTP date) waits 5 seconds."""
    header = "X-Esi-Error-Limit-Reset" if resp.status_code == 420 else "Retry-After"
    value = resp.headers.get(header) or resp.headers.get("Retry-After") or ""
    try:
        return max(0, int(value))
    except ValueError:
        return 5


class EsiClient:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=base_url or settings.ESI_BASE_URL,
            headers={
                "User-Agent": settings.ESI_USER_AGENT,
                "Accept": "application/json",
                "X-Compatibility-Date": settings.ESI_COMPAT_DATE,
            },
            timeout=20,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        use_etag: bool = True,
        token: str | None = None,
        character_id: int | None = None,
        with_pages: bool = False,
        with_meta: bool = False,
    ) -> Any:
        """One ESI call. `token` + `character_id` make an authenticated call. With
        `with_pages`, returns (body, X-Pages) instead of the body; with `with_meta`,
        (body, X-Pages, Last-Modified)."""
        if cache.get(BREAKER_KEY):
            raise EsiUnavailable("ESI circuit breaker open")
        if token is not None and character_id is None:
            raise ValueError("authenticated ESI calls need the character id for caching")
        key = _cache_key(method, path, params, json_body, character_id)
        cached = cache.get(key) if use_etag else None
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if cached and cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]

        for attempt in range(2):
            try:
                resp = self._client.request(
                    method, path, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:  # timeouts, DNS, refused connections
                raise EsiUnavailable(f"ESI unreachable on {path}: {exc}") from exc
            self._log_ratelimit(resp)
            if resp.status_code == 304 and cached:
                if with_meta:
                    return cached["body"], cached.get("pages", 1), cached.get("last_modified")
                return (cached["body"], cached.get("pages", 1)) if with_pages else cached["body"]
            if resp.status_code in (420, 429):
                retry_after = _wait_seconds(resp)
                if attempt == 0 and retry_after <= 10:
                    time.sleep(retry_after)
                    continue
                raise EsiRateLimited(retry_after)
            if resp.status_code >= 500:
                failures = cache.get("esi:5xx", 0) + 1
                cache.set("esi:5xx", failures, 120)
                if failures >= 3:
                    cache.set(BREAKER_KEY, True, BREAKER_SECONDS)
                    log.error("ESI breaker opened after %d consecutive 5xx", failures)
                raise EsiUnavailable(f"ESI {resp.status_code} on {path}")
            if resp.status_code >= 400:
                raise EsiError(f"ESI {resp.status_code} on {path}: {resp.text[:200]}")
            cache.delete("esi:5xx")
            try:
                body = resp.json()
            except ValueError as exc:
                raise EsiError(f"ESI sent a non-JSON body on {path}") from exc
            pages = int(resp.headers.get("X-Pages", "1") or 1)
            modified = resp.headers.get("Last-Modified")
            etag = resp.headers.get("ETag")
            if use_etag and etag:
                entry = {"etag": etag, "body": body, "pages": pages, "last_modified": modified}
                cache.set(key, entry, ETAG_TTL)
            if with_meta:
                return body, pages, modified
            return (body, pages) if with_pages else body
        raise EsiUnavailable("unreachable")

    @staticmethod
    def _log_ratelimit(resp: httpx.Response) -> None:
        remaining = resp.headers.get("X-Ratelimit-Remaining")
        if remaining is not None and remaining.isdigit() and int(remaining) < 20:
            log.warning(
                "ESI rate budget low: group=%s remaining=%s limit=%s",
                resp.headers.get("X-Ratelimit-Group"),
                remaining,
                resp.headers.get("X-Ratelimit-Limit"),
            )
        # Routes without a rate-limit group still count against the legacy error limit.
        errors_left = resp.headers.get("X-Esi-Error-Limit-Remain")
        if errors_left is not None and errors_left.isdigit() and int(errors_left) < 20:
            log.warning(
                "ESI error limit low: %s errors left, resets in %ss",
                errors_left,
                resp.headers.get("X-Esi-Error-Limit-Reset"),
            )

    def paged(
        self,
        path: str,
        *,
        token: str | None = None,
        character_id: int | None = None,
        params: dict | None = None,
    ) -> list:
        """All pages of an `X-Pages` route (assets, blueprints, market orders), concatenated.

        Every page must come from the same snapshot (the same `Last-Modified`): if ESI's cache
        turns over between pages, items that moved page would be read twice or not at all.
        On a mismatch the whole fetch starts again once; a second mismatch is an error, so
        the feed is recorded as failed and the previous rows stay."""
        for _ in range(2):
            first, pages, modified = self.request(
                "GET", path, params=params, token=token, character_id=character_id, with_meta=True
            )
            out = list(first)
            for page in range(2, pages + 1):
                body, _, page_modified = self.request(
                    "GET",
                    path,
                    params={**(params or {}), "page": page},
                    token=token,
                    character_id=character_id,
                    with_meta=True,
                )
                if modified and page_modified and page_modified != modified:
                    log.info("ESI %s changed between pages; fetching again", path)
                    break
                out.extend(body)
            else:
                return out
        raise EsiError(f"ESI {path} changed between pages twice; not used")

    def character_public(self, character_id: int) -> dict:
        return self.request("GET", f"/characters/{character_id}/")

    def affiliations(self, character_ids: list[int]) -> list[dict]:
        out: list[dict] = []
        ids = sorted(set(character_ids))
        for i in range(0, len(ids), 1000):
            out.extend(
                self.request("POST", "/characters/affiliation/", json_body=ids[i : i + 1000])
            )
        return out


_default: EsiClient | None = None


def get_client() -> EsiClient:
    global _default
    if _default is None:
        _default = EsiClient()
    return _default
