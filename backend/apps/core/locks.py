"""Cross-process locks for jobs that must not overlap (cron and CLI share the same tables)."""

import zlib
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections


def transaction_lock(name: str, *, using: str = "default") -> None:
    """Wait for a Postgres advisory lock held until the current transaction ends. Call it
    inside `transaction.atomic()`: writers that replace the same rows then run one after
    another instead of interleaving their deletes and inserts."""
    conn = connections[using]
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [zlib.crc32(name.encode())])


@contextmanager
def advisory_lock(key: int, *, using: str = "default") -> Iterator[bool]:
    """Try a Postgres session-level advisory lock; yields whether it was acquired.

    Released on exit or when the connection drops. Other database vendors always
    yield True because they never run the scheduler.
    """
    conn = connections[using]
    if conn.vendor != "postgresql":
        yield True
        return
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [key])
        acquired = bool(cur.fetchone()[0])
    try:
        yield acquired
    finally:
        if acquired:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [key])
