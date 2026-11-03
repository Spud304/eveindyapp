"""Raw layer: stream included files from a source into SdeRawRecord, then derive typed tables."""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.db import transaction

from apps.core.importing import ImportFailed, ImportReport

from . import derive
from .constants import RAW_BATCH_SIZE
from .jsonl import SdeSource, iter_records
from .models import SdeBuild, SdeRawRecord

log = logging.getLogger(__name__)


def included_files() -> list[str]:
    return list(settings.SDE_INCLUDED_FILES)


def import_source(
    source: SdeSource,
    *,
    build: int,
    release_date: datetime | None = None,
    files: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    raw_only: bool = False,
) -> ImportReport:
    """Load `files` (default: the configured include list) for `build`, then derive typed tables."""
    report = ImportReport(source=f"{source.description} (build {build})")
    latest = SdeBuild.latest()
    if latest is not None and build < latest.build and not force:
        raise ImportFailed(
            f"build {build} is older than the imported build {latest.build}",
            "pass --force to re-import an older build (records only the newer build has are marked removed)",
        )

    wanted = files or included_files()
    available = set(source.names())
    # One transaction for every file and the derivation: a file that fails part way leaves the
    # database on the previous build, never on a mix of two.
    with transaction.atomic():
        for name in wanted:
            if name not in available:
                report.warn(f"{name}.jsonl not present in {source.description}; skipped")
                continue
            load_raw_file(source, name, build, report, dry_run=dry_run)
        if not dry_run and not raw_only:
            derive.derive_all(build, release_date, report)
    report.finish()
    return report


def load_raw_file(
    source: SdeSource, name: str, build: int, report: ImportReport, *, dry_run: bool = False
) -> None:
    """Upsert every record of one file, then flag the ones that vanished."""
    counts = report.file(name)
    started = time.monotonic()
    warnings: list[str] = []
    batch: list[SdeRawRecord] = []

    def flush() -> None:
        if batch and not dry_run:
            SdeRawRecord.objects.bulk_create(
                batch,
                batch_size=RAW_BATCH_SIZE,
                update_conflicts=True,
                unique_fields=["file", "key"],
                update_fields=["data", "build", "removed"],
            )
        counts.upserted += len(batch)
        batch.clear()

    with transaction.atomic(), source.open(name) as text:
        for key, data in iter_records(text, file=name, warnings=warnings):
            counts.seen += 1
            batch.append(SdeRawRecord(file=name, key=key, data=data, build=build, removed=False))
            if len(batch) >= RAW_BATCH_SIZE:
                flush()
        flush()
        if not dry_run:
            # Anything this build did not carry, older or (after a forced downgrade) newer.
            counts.removed = (
                SdeRawRecord.objects.filter(file=name, removed=False)
                .exclude(build=build)
                .update(removed=True)
            )

    counts.seconds = time.monotonic() - started
    if warnings:
        report.warn(f"{name}: {len(warnings)} decode warnings, first: {warnings[0]}")
    log.info(
        "%s: %d records upserted, %d removed in %.1fs%s",
        name,
        counts.upserted,
        counts.removed,
        counts.seconds,
        " (dry run)" if dry_run else "",
    )
