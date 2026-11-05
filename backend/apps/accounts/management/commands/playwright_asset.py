from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.esidata.models import Asset
from apps.planning.models import Station

from .playwright_cleanup import FIRST, LAST


class Command(BaseCommand):
    help = (
        "Put a stack of items in a browser-test character's hangar (reserved ids only), and "
        "optionally place one of its account's stations at that location."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--character", type=int, required=True)
        parser.add_argument("--item-id", type=int, required=True)
        parser.add_argument("--type", type=int, required=True)
        parser.add_argument("--quantity", type=int, required=True)
        # Use structure-range ids (>= 1e12): no name lookup is made for them.
        parser.add_argument("--location", type=int, required=True)
        parser.add_argument(
            "--station", type=int, help="this station's location becomes --location"
        )

    def handle(self, *args, **o) -> None:
        if not FIRST <= o["character"] <= LAST:
            raise CommandError(f"only browser-test characters ({FIRST}-{LAST})")
        if not FIRST <= o["item_id"] <= LAST:
            raise CommandError(f"item ids must be in {FIRST}-{LAST} so cleanup finds them")
        if o["station"] is not None:
            placed = Station.objects.filter(
                pk=o["station"], user__characters__character_id=o["character"]
            ).update(location_id=o["location"])
            if not placed:
                raise CommandError("the station must belong to the test character's account")
        Asset.objects.update_or_create(
            owner_kind="character",
            owner_id=o["character"],
            item_id=o["item_id"],
            defaults={
                "type_id": o["type"],
                "quantity": o["quantity"],
                "location_id": o["location"],
                "location_type": "other",
                "location_flag": "Hangar",
                "is_singleton": False,
                "root_location_id": o["location"],
                "hangar_flag": "Hangar",
            },
        )
        self.stdout.write(f"{o['quantity']} x {o['type']} for {o['character']}")
