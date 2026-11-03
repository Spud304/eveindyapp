"""Drop-folder trigger: any settled zip in instance/sde/incoming is imported, then archived."""

import logging
import os
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from apps.core.importing import ImportFailed, ImportReport

from .constants import INCOMING_SETTLE_SECONDS
from .jsonl import ZipSource, detect_build
from .loader import import_source

log = logging.getLogger(__name__)


def sde_dirs() -> dict[str, Path]:
    """Create and return the instance/sde subdirectories."""
    base = Path(settings.SDE_DIR)
    dirs = {name: base / name for name in ("incoming", "archive", "failed", "downloads")}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def eligible_zips(incoming: Path, now: float | None = None) -> list[Path]:
    """Zips old enough to be fully copied and structurally valid."""
    now = time.time() if now is None else now
    found = []
    for path in sorted(incoming.glob("*.zip")):
        if path.name.startswith("."):
            continue
        if now - path.stat().st_mtime < INCOMING_SETTLE_SECONDS:
            log.info("%s is still settling; skipped this pass", path.name)
            continue
        if not zipfile.is_zipfile(path):
            log.info("%s is not a complete zip yet; skipped this pass", path.name)
            continue
        found.append(path)
    return found


def move_to(path: Path, dest_dir: Path) -> Path:
    target = dest_dir / path.name
    if target.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        target = dest_dir / f"{path.stem}-{stamp}{path.suffix}"
    os.replace(path, target)
    return target


def scan_incoming(*, force: bool = False, files: list[str] | None = None) -> list[ImportReport]:
    """Import every eligible zip in incoming/. Successes go to archive/, failures to failed/."""
    dirs = sde_dirs()
    reports: list[ImportReport] = []
    for path in eligible_zips(dirs["incoming"]):
        try:
            with ZipSource(path) as source:
                build, release_date = detect_build(source, path=path)
                report = import_source(
                    source, build=build, release_date=release_date, files=files, force=force
                )
            reports.append(report)
            moved = move_to(path, dirs["archive"])
            log.info("archived %s as %s", path.name, moved)
        except Exception as exc:
            # Any failure, not only ImportFailed (a CRC error mid-stream, a bad row): left in
            # incoming/, the zip would be retried every pass and block the ones behind it.
            remediation = getattr(exc, "remediation", "") or "see the log for the traceback"
            moved = move_to(path, dirs["failed"])
            note = moved.with_suffix(moved.suffix + ".error.txt")
            note.write_text(f"{type(exc).__name__}: {exc}\n{remediation}\n", encoding="utf-8")
            if isinstance(exc, ImportFailed):
                log.error(
                    "import of %s failed: %s (%s); moved to %s", path.name, exc, remediation, moved
                )
            else:
                log.exception("import of %s crashed; moved to %s", path.name, moved)
            failed = ImportReport(source=str(path))
            failed.fail(str(exc))
            failed.finish()
            reports.append(failed)
    if not reports:
        log.info("incoming: nothing to import")
    return reports
