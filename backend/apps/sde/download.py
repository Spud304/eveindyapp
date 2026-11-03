"""Fetch CCP's build pointer and the JSONL zip into the instance downloads folder."""

import json
import logging
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from django.conf import settings

from apps.core.importing import ImportFailed

from .constants import (
    BUILD_FILENAME_RE,
    DOWNLOAD_BACKOFF_SECONDS,
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_FALLBACK_BYTES,
    DOWNLOAD_HEADROOM,
    DOWNLOAD_RETRIES,
    DOWNLOADS_TO_KEEP,
)
from .jsonl import ZipSource, read_build_info

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LatestBuild:
    build: int
    release_date: datetime | None


def make_client(**kwargs) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=120.0),
        headers={"User-Agent": settings.ESI_USER_AGENT},
        **kwargs,
    )


def fetch_latest_build(client: httpx.Client | None = None) -> LatestBuild:
    """Read CCP's latest.jsonl: one line, {"_key": "sde", "buildNumber": N, "releaseDate": ...}."""
    client = client or make_client()
    try:
        resp = client.get(settings.SDE_LATEST_URL)
    except httpx.TransportError as exc:
        raise ImportFailed(f"latest.jsonl unreachable: {exc}", "retry later") from exc
    if resp.status_code != 200:
        raise ImportFailed(
            f"latest.jsonl returned HTTP {resp.status_code}",
            "CCP's static-data site may be down; retry later",
        )
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue  # not JSON: keep looking, and fail below if no line was the build pointer
        if isinstance(record, dict) and record.get("_key") == "sde" and "buildNumber" in record:
            release = record.get("releaseDate")
            parsed = datetime.fromisoformat(release.replace("Z", "+00:00")) if release else None
            return LatestBuild(int(record["buildNumber"]), parsed)
    raise ImportFailed(
        "latest.jsonl has no 'sde' record", "CCP may have changed the build pointer format"
    )


def download_path(dest_dir: Path, build: int) -> Path:
    return Path(dest_dir) / f"eve-online-static-data-{build}-jsonl.zip"


def download_build(build: int, dest_dir: Path, client: httpx.Client | None = None) -> Path:
    """Stream the latest zip to dest_dir atomically and verify it is the expected build."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = download_path(dest_dir, build)
    if final.exists() and zipfile.is_zipfile(final):
        with ZipSource(final) as source:
            info = read_build_info(source)
        if info is not None and info[0] == build:
            log.info("build %d already downloaded: %s", build, final)
            return final
        log.warning("%s is not build %d; downloading again", final, build)
        final.unlink()
    client = client or make_client()
    partial = dest_dir / f".partial-{build}.zip"
    last_error: Exception | None = None
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            _stream_to(client, settings.SDE_DOWNLOAD_URL, partial)
            break
        except (httpx.TransportError, _RetryableHttpError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < DOWNLOAD_RETRIES - 1:
                delay = DOWNLOAD_BACKOFF_SECONDS[min(attempt, len(DOWNLOAD_BACKOFF_SECONDS) - 1)]
                log.warning(
                    "download attempt %d failed (%s); retrying in %ds", attempt + 1, exc, delay
                )
                time.sleep(delay)
    else:
        raise ImportFailed(
            f"download failed after {DOWNLOAD_RETRIES} attempts: {last_error}", "retry later"
        )

    if not zipfile.is_zipfile(partial):
        partial.unlink(missing_ok=True)
        raise ImportFailed(
            "downloaded file is not a zip", "retry; if it persists CCP's download may be broken"
        )
    with ZipSource(partial) as source:
        info = read_build_info(source)
    if info is None:
        partial.unlink(missing_ok=True)
        raise ImportFailed(
            "downloaded archive has no _sde.jsonl build record",
            "retry; if it persists CCP's download may be broken",
        )
    if info[0] != build:
        partial.unlink(missing_ok=True)
        raise ImportFailed(
            f"downloaded archive is build {info[0]}, expected {build}",
            "CCP published a new build mid-download; run --check-latest again",
        )
    os.replace(partial, final)
    log.info("downloaded build %d to %s (%.1f MB)", build, final, final.stat().st_size / 1e6)
    return final


class _RetryableHttpError(Exception):
    pass


def _stream_to(client: httpx.Client, url: str, target: Path) -> None:
    with client.stream("GET", url) as resp:
        if resp.status_code >= 500:
            raise _RetryableHttpError(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ImportFailed(
                f"download returned HTTP {resp.status_code}", "check SDE_DOWNLOAD_URL"
            )
        length = resp.headers.get("Content-Length")
        expected = int(length) if length and length.isdigit() else None
        needed = int((expected or DOWNLOAD_FALLBACK_BYTES) * DOWNLOAD_HEADROOM)
        free = shutil.disk_usage(target.parent).free
        if free < needed:
            raise ImportFailed(
                f"need about {needed >> 20} MB free in {target.parent}, have {free >> 20} MB",
                "free disk space or point INSTANCE_DIR at a larger volume",
            )
        written = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                fh.write(chunk)
                written += len(chunk)
        if expected is not None and written != expected:
            raise _RetryableHttpError(f"short read: {written} of {expected} bytes")


def prune_downloads(dest_dir: Path, keep: int = DOWNLOADS_TO_KEEP) -> list[Path]:
    """Delete all but the newest `keep` archives by build number; returns what was removed."""
    dest_dir = Path(dest_dir)
    if not dest_dir.exists():
        return []
    archives = []
    for path in dest_dir.glob("*.zip"):
        match = BUILD_FILENAME_RE.search(path.name)
        if match:
            archives.append((int(match.group(1)), path))
    archives.sort(reverse=True)
    removed = []
    for _, path in archives[keep:]:
        path.unlink()
        removed.append(path)
        log.info("pruned old SDE archive %s", path.name)
    return removed
