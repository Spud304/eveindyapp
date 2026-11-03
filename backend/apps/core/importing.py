"""Shared reporting types for bulk importers (SDE now; YAML rulesets and xlsx later)."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


class ImportFailed(Exception):
    """An import could not proceed. `remediation` tells the operator what to do about it."""

    def __init__(self, message: str, remediation: str = ""):
        super().__init__(message)
        self.remediation = remediation


@dataclass
class FileCounts:
    seen: int = 0
    upserted: int = 0
    removed: int = 0
    seconds: float = 0.0


@dataclass
class ImportReport:
    source: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    files: dict[str, FileCounts] = field(default_factory=dict)
    derived: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def duration_s(self) -> float:
        end = self.finished_at or datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    def file(self, name: str) -> FileCounts:
        return self.files.setdefault(name, FileCounts())

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC)

    def summary(self) -> str:
        lines = [
            f"import from {self.source}: {'ok' if self.ok else 'FAILED'} in {self.duration_s:.1f}s"
        ]
        for name, counts in self.files.items():
            lines.append(
                f"  {name}: {counts.seen} seen, {counts.upserted} upserted, "
                f"{counts.removed} removed ({counts.seconds:.1f}s)"
            )
        for model, count in self.derived.items():
            lines.append(f"  derived {model}: {count}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        for e in self.errors:
            lines.append(f"  error: {e}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data
