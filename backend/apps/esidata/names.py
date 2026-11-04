"""Names for characters, corporations and NPC stations, via ESI `/universe/names`, cached a day.

Upwell structure ids are not accepted there (ESI rejects the whole request), so they are left
out; callers name structures from the account's stations instead.
"""

import logging
from collections.abc import Iterable

from django.core.cache import cache

from apps.esi.client import EsiClient, EsiError, get_client

log = logging.getLogger(__name__)

TTL = 24 * 3600
STRUCTURE_MIN_ID = 1_000_000_000_000
BATCH = 1000


def _key(i: int) -> str:
    return f"name:{i}"


def resolve(ids: Iterable[int], client: EsiClient | None = None) -> dict[int, str]:
    wanted = {int(i) for i in ids if i and int(i) < STRUCTURE_MIN_ID}
    if not wanted:
        return {}
    cached = cache.get_many([_key(i) for i in wanted])
    out = {i: cached[_key(i)] for i in wanted if _key(i) in cached}
    missing = sorted(wanted - set(out))
    if missing:
        client = client or get_client()
        for n in range(0, len(missing), BATCH):
            chunk = missing[n : n + BATCH]
            try:
                rows = client.request("POST", "/universe/names/", json_body=chunk, use_etag=False)
            except EsiError as exc:
                # One unknown id fails the whole request; names are cosmetic, so carry on.
                log.warning("name lookup failed for %d ids: %s", len(chunk), exc)
                continue
            found = {int(r["id"]): str(r["name"]) for r in rows}
            cache.set_many({_key(i): name for i, name in found.items()}, TTL)
            out.update(found)
    return out
