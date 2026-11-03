"""Streaming readers for CCP's JSONL SDE: zip or directory sources, pair decoding, build detection."""

import io
import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TextIO

from apps.core.importing import ImportFailed

from .constants import BUILD_FILENAME_RE, BUILD_INFO_FILE

log = logging.getLogger(__name__)

WRONG_FORMAT_HINT = (
    "expected the JSONL SDE published since September 2025 at "
    "https://developers.eveonline.com/docs/services/static-data/"
)


def _is_pair_list(value: list) -> bool:
    return bool(value) and all(isinstance(item, dict) and "_key" in item for item in value)


def decode_pairs(value: Any, warnings: list[str] | None = None, path: str = "") -> Any:
    """Turn CCP's `[{"_key": k, "_value": v}, ...]` integer-key encoding back into dicts, recursively.

    Items without `_value` are the value themselves minus `_key`. Lists mixing keyed and
    unkeyed items are left as lists and reported as a warning.
    """
    if isinstance(value, list):
        if _is_pair_list(value):
            out: dict[Any, Any] = {}
            for item in value:
                key = item["_key"]
                if "_value" in item:
                    if len(item) > 2 and warnings is not None:
                        warnings.append(
                            f"{path}: pair entry {key!r} has extra fields beside _value"
                        )
                    out[key] = decode_pairs(item["_value"], warnings, f"{path}[{key}]")
                else:
                    rest = {k: v for k, v in item.items() if k != "_key"}
                    out[key] = decode_pairs(rest, warnings, f"{path}[{key}]")
            return out
        if warnings is not None and any(isinstance(i, dict) and "_key" in i for i in value):
            warnings.append(f"{path}: list mixes keyed and unkeyed items; left as list")
        return [decode_pairs(item, warnings, f"{path}[]") for item in value]
    if isinstance(value, dict):
        return {
            k: decode_pairs(v, warnings, f"{path}.{k}" if path else k) for k, v in value.items()
        }
    return value


def iter_records(
    text: TextIO, *, file: str, warnings: list[str] | None = None
) -> Iterator[tuple[str, dict]]:
    """Yield (key, decoded record) per non-blank line. The top-level `_key` is stripped."""
    for lineno, line in enumerate(text, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImportFailed(
                f"{file}.jsonl line {lineno}: invalid JSON ({exc.msg})", WRONG_FORMAT_HINT
            ) from exc
        if not isinstance(raw, dict) or "_key" not in raw:
            raise ImportFailed(f"{file}.jsonl line {lineno}: record has no _key", WRONG_FORMAT_HINT)
        key = raw.pop("_key")
        yield str(key), decode_pairs(raw, warnings, f"{file}[{key}]")


class SdeSource(Protocol):
    description: str

    def names(self) -> list[str]: ...

    def open(self, name: str) -> TextIO: ...

    def close(self) -> None: ...


class ZipSource:
    """A CCP SDE zip. `.jsonl` members are found at any depth and keyed by file stem."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.description = str(self.path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as exc:
            raise ImportFailed(
                f"{self.path} is not a valid zip file", "re-download the SDE archive"
            ) from exc
        self._members: dict[str, zipfile.ZipInfo] = {}
        for info in self._zip.infolist():
            posix = PurePosixPath(info.filename)
            if info.is_dir() or posix.suffix != ".jsonl":
                continue
            stem = posix.stem
            if stem in self._members:
                raise ImportFailed(f"{self.path}: duplicate member {stem}.jsonl", WRONG_FORMAT_HINT)
            self._members[stem] = info

    def names(self) -> list[str]:
        return sorted(self._members)

    def open(self, name: str) -> TextIO:
        if name not in self._members:
            raise KeyError(name)
        return io.TextIOWrapper(self._zip.open(self._members[name]), encoding="utf-8-sig")

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class DirSource:
    """A directory of loose `.jsonl` files, for offline or partial imports."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.description = str(self.path)
        self._files = {p.stem: p for p in sorted(self.path.glob("*.jsonl"))}
        if not self._files:
            raise ImportFailed(
                f"{self.path} contains no .jsonl files",
                "point --path at the SDE zip or an extracted folder",
            )

    def names(self) -> list[str]:
        return sorted(self._files)

    def open(self, name: str) -> TextIO:
        return self._files[name].open(encoding="utf-8-sig")

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_source(path: Path) -> ZipSource | DirSource:
    path = Path(path)
    if path.is_dir():
        return DirSource(path)
    if path.is_file():
        return ZipSource(path)
    raise ImportFailed(f"{path} does not exist", "check the --path argument")


def read_build_info(source: SdeSource) -> tuple[int, datetime | None] | None:
    """Read `_sde.jsonl` if present: (buildNumber, releaseDate)."""
    if BUILD_INFO_FILE not in source.names():
        return None
    with source.open(BUILD_INFO_FILE) as text:
        for key, record in iter_records(text, file=BUILD_INFO_FILE):
            if key == "sde" and "buildNumber" in record:
                release = record.get("releaseDate")
                parsed = datetime.fromisoformat(release.replace("Z", "+00:00")) if release else None
                return int(record["buildNumber"]), parsed
    return None


def detect_build(
    source: SdeSource, *, path: Path | None = None, override: int | None = None
) -> tuple[int, datetime | None]:
    """Resolve the build number: explicit override, then `_sde.jsonl`, then the CCP filename."""
    info = read_build_info(source)
    if override is not None:
        if info is not None and info[0] != override:
            log.warning(
                "%s says build %d; importing as build %d (--build)",
                source.description,
                info[0],
                override,
            )
        return override, info[1] if info else None
    if info is not None:
        return info
    if path is not None:
        match = BUILD_FILENAME_RE.search(Path(path).name)
        if match:
            return int(match.group(1)), None
    raise ImportFailed(
        f"cannot determine the SDE build for {source.description}",
        "the archive has no _sde.jsonl and the filename is not eve-online-static-data-<build>-jsonl.zip; pass --build N",
    )
