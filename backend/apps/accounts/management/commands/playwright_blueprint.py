from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.esidata.models import BlueprintItem

from .playwright_cleanup import FIRST, LAST

TEST_LOCATION = 1_000_000_000_001  # structure-range id, so no name lookup is made for it


class Command(BaseCommand):
    help = "Create a BPC for a browser-test character (reserved ids only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--character", type=int, required=True)
        parser.add_argument("--item-id", type=int, required=True)
        parser.add_argument("--blueprint", type=int, required=True)
        parser.add_argument("--runs", type=int, default=10)
        parser.add_argument("--me", type=int, default=10)
        parser.add_argument("--te", type=int, default=20)

    def handle(self, *args, **o) -> None:
        if not FIRST <= o["character"] <= LAST:
            raise CommandError(f"only browser-test characters ({FIRST}-{LAST})")
        if not FIRST <= o["item_id"] <= LAST:
            raise CommandError(f"item ids must be in {FIRST}-{LAST} so cleanup finds them")
        BlueprintItem.objects.update_or_create(
            owner_kind="character",
            owner_id=o["character"],
            item_id=o["item_id"],
            defaults={
                "type_id": o["blueprint"],
                "location_id": TEST_LOCATION,
                "location_flag": "Hangar",
                "quantity": -2,
                "runs": o["runs"],
                "material_efficiency": o["me"],
                "time_efficiency": o["te"],
                "root_location_id": TEST_LOCATION,
                "hangar_flag": "Hangar",
            },
        )
        self.stdout.write(f"BPC {o['item_id']} for {o['character']}")
