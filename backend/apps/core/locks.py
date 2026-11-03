"""Cross-process locks for jobs that must not overlap (cron and CLI share the same tables)."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections


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
