from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import EveCharacter, User
from apps.esidata import sync


class Command(BaseCommand):
    help = "Fetch ESI data: an account's characters and corps, one character, or public prices."

    def add_arguments(self, parser: CommandParser) -> None:
        who = parser.add_mutually_exclusive_group(required=True)
        who.add_argument("--account", type=int, help="user id: all linked characters and corps")
        who.add_argument("--character", type=int, help="one character id (character feeds only)")
        who.add_argument("--all", action="store_true", help="every account with a linked character")
        who.add_argument("--public", action="store_true", help="market prices and cost indices")

    def handle(self, *args, **options) -> None:
        if options["public"]:
            counts = sync.sync_public()
            self.stdout.write(f"public: {counts}")
            return
        if options["character"]:
            ch = EveCharacter.objects.filter(pk=options["character"]).first()
            if ch is None:
                raise CommandError("unknown character")
            self._report(sync.sync_character(ch))
            return
        users = (
            User.objects.filter(pk=options["account"])
            if options["account"]
            else User.objects.filter(characters__esi_token__isnull=False).distinct()
        )
        if not users:
            raise CommandError("no matching account")
        for user in users:
            self.stdout.write(f"account {user.pk} ({user})")
            self._report(sync.sync_account(user))

    def _report(self, statuses) -> None:
        for s in statuses:
            source = f" via {s.source_character}" if s.source_character else ""
            outcome = f"{s.rows} rows" if s.ok else f"FAILED: {s.error}"
            self.stdout.write(f"  {s.owner_kind} {s.owner_id} {s.feed}{source}: {outcome}")
