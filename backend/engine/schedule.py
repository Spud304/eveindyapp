"""Dependency-aware list scheduling of planned jobs onto character slots."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import formulas as f
from .types import Activity, Character, Reason, ReasonCode, SkillRequirement


@dataclass
class WorkJob:
    """Mutable job used while planning; frozen into `PlannedJob` at the end."""

    job_id: str
    activity: Activity
    blueprint_type_id: int
    runs: int
    time_per_run: float  # SDE base time
    time_multiplier: float  # blueprint TE x station; skills applied per character
    skills: tuple[SkillRequirement, ...]
    copies: int = 1
    depends_on: list[str] = field(default_factory=list)
    dep_items: set[int] = field(default_factory=set)  # resolved into depends_on
    # Filled by schedule()
    character: Character | None = None
    start: float = 0.0
    end: float = 0.0
    schedule_reason: Reason | None = None

    def duration(self, character: Character | None) -> float:
        return (
            self.time_per_run
            * self.runs
            * self.copies
            * self.time_multiplier
            * f.skill_time_multiplier(self.activity, character)
        )


_SLOT_KIND = {
    Activity.MANUFACTURING: "mfg",
    Activity.REACTION: "reaction",
    Activity.COPYING: "science",
    Activity.INVENTION: "science",
}


def schedule(jobs: list[WorkJob], characters: tuple[Character, ...]) -> float:
    """Assign each job a character, start and end. Jobs start once every job
    they depend on has ended. Among ready jobs the longest goes first (LPT);
    each goes to the eligible slot that finishes it earliest. Returns the
    wall-clock end of the last job."""
    by_id = {j.job_id: j for j in jobs}
    free: dict[tuple[int, str], list[float]] = {}
    for ch in characters:
        for activity, kind in _SLOT_KIND.items():
            free.setdefault((ch.character_id, kind), [0.0] * f.slots(ch, activity))

    pending = {j.job_id for j in jobs}
    done: set[str] = set()
    while pending:
        ready = [
            by_id[i] for i in pending if all(d in done for d in by_id[i].depends_on)
        ]
        if not ready:
            raise ValueError("job dependency cycle")
        job = max(ready, key=lambda j: (j.duration(None), j.job_id))
        ready_at = max((by_id[d].end for d in job.depends_on), default=0.0)
        _place(job, ready_at, characters, free)
        pending.discard(job.job_id)
        done.add(job.job_id)
    return max((j.end for j in jobs), default=0.0)


def _place(job: WorkJob, ready_at: float, characters, free) -> None:
    kind = _SLOT_KIND[job.activity]
    eligible = [
        ch
        for ch in characters
        if job.activity in ch.activities and f.skills_met(ch, job.skills)
    ]
    best = None
    for ch in eligible:
        slots = free[(ch.character_id, kind)]
        idx = min(range(len(slots)), key=lambda i: slots[i])
        start = max(slots[idx], ready_at)
        end = start + job.duration(ch)
        if best is None or end < best[0]:
            best = (end, start, ch, idx)

    if best is None:
        job.character = None
        job.start = ready_at
        job.end = ready_at + job.duration(None)
        missing = ", ".join(f"{r.skill_id} L{r.level}" for r in job.skills) or "none"
        job.schedule_reason = Reason(
            ReasonCode.UNSCHEDULED_NO_CHARACTER,
            f"No character is allowed to run {job.activity.value} with the required "
            f"skills ({missing}); timed with no skills.",
        )
        return

    end, start, ch, idx = best
    free[(ch.character_id, kind)][idx] = end
    job.character, job.start, job.end = ch, start, end
    waited = " after its inputs finish" if start == ready_at and ready_at > 0 else ""
    job.schedule_reason = Reason(
        ReasonCode.SCHEDULED,
        f"{ch.name}: earliest finish of {len(eligible)} eligible character(s){waited}.",
    )
