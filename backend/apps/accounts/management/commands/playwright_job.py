from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.esidata.models import IndustryJob

from .playwright_cleanup import FIRST, LAST


class Command(BaseCommand):
    help = "Create an industry job for a browser-test character (reserved ids only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--character", type=int, required=True)
        parser.add_argument("--job-id", type=int, required=True)
        parser.add_argument("--blueprint", type=int, required=True)
        parser.add_argument("--product", type=int)
        parser.add_argument("--activity", type=int, default=1)
        parser.add_argument("--runs", type=int, default=1)
        parser.add_argument("--status", default="active")
        parser.add_argument("--started-minutes-ago", type=int, default=1)
        parser.add_argument("--blueprint-item", type=int, default=1, help="installed item id")

    def handle(self, *args, **o) -> None:
        if not FIRST <= o["character"] <= LAST:
            raise CommandError(f"only browser-test characters ({FIRST}-{LAST})")
        if not FIRST <= o["job_id"] <= LAST:
            raise CommandError(f"job ids must be in {FIRST}-{LAST} so cleanup finds them")
        start = timezone.now() - timedelta(minutes=o["started_minutes_ago"])
        IndustryJob.objects.update_or_create(
            job_id=o["job_id"],
            defaults={
                "owner_kind": "character",
                "owner_id": o["character"],
                "installer_id": o["character"],
                "facility_id": 1,
                "location_id": 1,
                "activity_id": o["activity"],
                "blueprint_id": o["blueprint_item"],
                "blueprint_type_id": o["blueprint"],
                "blueprint_location_id": 1,
                "output_location_id": 1,
                "product_type_id": o["product"],
                "runs": o["runs"],
                "status": o["status"],
                "duration": 3600,
                "start_date": start,
                "end_date": start + timedelta(hours=4),
                "last_seen_at": timezone.now(),
            },
        )
        self.stdout.write(f"job {o['job_id']} for {o['character']}")
