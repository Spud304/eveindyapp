"""Industry job helpers shared by the overview API and planning inputs."""

from datetime import datetime

from apps.accounts.models import User

from .access import owner_q
from .models import Feed, IndustryJob

ACTIVITY_NAMES = {
    1: "manufacturing",
    3: "research_time",
    4: "research_material",
    5: "copying",
    8: "invention",
    9: "reaction",
}  # [client]
OPEN_STATUSES = ("active", "paused", "ready")


def effective_status(job: IndustryJob, now: datetime) -> str:
    """The client calls an installed job past its end date "ready" (industryCommon.JobStatus);
    ESI's status can lag until the next sync."""
    if job.status == "active" and job.end_date <= now:
        return "ready"
    return job.status


def blueprint_jobs(user: User) -> dict[int, IndustryJob]:
    """Open jobs (not yet delivered) the account can read, by the blueprint item installed in
    them. A blueprint in a job is not in its hangar until the job is delivered."""
    jobs = IndustryJob.objects.filter(owner_q(user, Feed.JOBS), status__in=OPEN_STATUSES)
    return {j.blueprint_id: j for j in jobs.order_by("start_date")}
