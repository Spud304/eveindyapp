"""Dependency-aware list scheduling of planned jobs onto character slots."""

from __future__ import annotations

from collections.abc import Mapping
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
    # Blueprint item the job is installed with: jobs with the same lock never overlap, since
    # one blueprint is in one job at a time. None for a blueprint used by this job only.
    lock: str | None = None
    # Only these characters may run the job (None: anyone eligible). Invention uses it so the
    # attempts counted with one character's chance are run at that chance.
    characters: frozenset[int] | None = None
    depends_on: list[str] = field(default_factory=list)
    dep_items: set[int] = field(default_factory=set)  # resolved into depends_on
    # Required-skill time bonuses (manufacturing only); see GameData.skill_time_bonuses
    skill_time_bonuses: Mapping[int, float] = field(default_factory=dict)
    # Filled by schedule()
    character: Character | None = None
    start: float = 0.0
    end: float = 0.0
    schedule_reason: Reason | None = None

    def duration(self, character: Character | None) -> float:
        seconds = (
            self.time_per_run
            * self.runs
            * self.copies
            * self.time_multiplier
            * f.skill_time_multiplier(self.activity, character)
        )
        if self.activity == Activity.MANUFACTURING:
            seconds *= f.required_skill_time_multiplier(
                self.skills, self.skill_time_bonuses, character
            )
        return float(f.round_half_up(seconds))  # the client rounds job time to seconds


_SLOT_KIND = {
    Activity.MANUFACTURING: "mfg",
    Activity.REACTION: "reaction",
    Activity.COPYING: "science",
    Activity.INVENTION: "science",
}


def schedule(
    jobs: list[WorkJob],
    characters: tuple[Character, ...],
    locks: Mapping[str, float] | None = None,
) -> float:
    """Assign each job a character, start and end. Jobs start once every job
    they depend on has ended. Among ready jobs the longest goes first (LPT);
    each goes to the eligible slot that finishes it earliest, and not before
    its blueprint is free. `locks` gives blueprints that are busy at the start (in a job
    already running) the time they become free. Returns the wall-clock end of the last job."""
    by_id = {j.job_id: j for j in jobs}
    free: dict[tuple[int, str], list[float]] = {}
    for ch in characters:
        for activity, kind in _SLOT_KIND.items():
            free.setdefault((ch.character_id, kind), [0.0] * f.slots(ch, activity))

    locks = dict(locks or {})
    # Durations without skills order the ready jobs; computed once per job.
    longest = {j.job_id: j.duration(None) for j in jobs}
    waiting = {j.job_id: set(j.depends_on) for j in jobs}
    dependents: dict[str, list[str]] = {}
    for j in jobs:
        for d in waiting[j.job_id]:
            dependents.setdefault(d, []).append(j.job_id)
    ready_ids = {i for i, deps in waiting.items() if not deps}
    pending = {j.job_id for j in jobs}
    while pending:
        if not ready_ids:
            raise ValueError("job dependency cycle")
        job = by_id[max(ready_ids, key=lambda i: (longest[i], i))]
        ready_ids.discard(job.job_id)
        ready_at = max((by_id[d].end for d in job.depends_on), default=0.0)
        if job.lock is not None:
            ready_at = max(ready_at, locks.get(job.lock, 0.0))
        _place(job, ready_at, characters, free)
        if job.lock is not None:
            locks[job.lock] = job.end
        pending.discard(job.job_id)
        for nxt in dependents.get(job.job_id, ()):
            waiting[nxt].discard(job.job_id)
            if not waiting[nxt]:
                ready_ids.add(nxt)
    return max((j.end for j in jobs), default=0.0)


def _place(job: WorkJob, ready_at: float, characters, free) -> None:
    kind = _SLOT_KIND[job.activity]
    eligible = [
        ch
        for ch in characters
        if job.activity in ch.activities
        and f.skills_met(ch, job.skills)
        and (job.characters is None or ch.character_id in job.characters)
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
    waited = (
        " after its inputs and blueprint are ready" if start == ready_at and ready_at > 0 else ""
    )
    job.schedule_reason = Reason(
        ReasonCode.SCHEDULED,
        f"{ch.name}: earliest finish of {len(eligible)} eligible character(s){waited}.",
    )
