from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import EveCharacter, User
from apps.esidata.models import Asset, BlueprintItem, IndustryJob

# Character ids reserved for browser tests (playwright_tests/conftest.py). Real EVE character
# ids are far outside this range, so nothing else can match.
FIRST, LAST = 900_000_001, 900_000_099


class Command(BaseCommand):
    help = "Delete the accounts, characters, plans and stations the browser tests created."

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            chars = EveCharacter.objects.filter(character_id__range=(FIRST, LAST))
            users = User.objects.filter(characters__in=chars).distinct()
            # Plans, stations and build rules cascade from the account; tokens from the character.
            n_users = users.count()
            users.delete()
            n_chars, _ = chars.delete()
            # Jobs made by `playwright_job` (their links went with the accounts).
            IndustryJob.objects.filter(
                job_id__range=(FIRST, LAST), owner_id__range=(FIRST, LAST)
            ).delete()
            # BPCs made by `playwright_blueprint`.
            BlueprintItem.objects.filter(
                item_id__range=(FIRST, LAST), owner_id__range=(FIRST, LAST)
            ).delete()
            # Stacks made by `playwright_asset`.
            Asset.objects.filter(
                item_id__range=(FIRST, LAST), owner_id__range=(FIRST, LAST)
            ).delete()
        self.stdout.write(
            f"playwright_cleanup: removed {n_users} accounts, {n_chars} character rows"
        )
