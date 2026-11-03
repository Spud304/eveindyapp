import zlib

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import EveCharacter, User
from apps.core.locks import advisory_lock
from apps.esidata import sync
from apps.esidata.models import Feed


def _lock_key(mode: str) -> int:
    """One Postgres advisory lock per run mode, so the same cron line cannot overlap itself
    while different modes (e.g. hourly full and 10-minute jobs) may run side by side."""
    return zlib.crc32(f"sync_esi:{mode}".encode())


class Command(BaseCommand):
    help = "Fetch ESI data: an account's characters and corps, one character, or public prices."

    def add_arguments(self, parser: CommandParser) -> None:
        who = parser.add_mutually_exclusive_group(required=True)
        who.add_argument("--account", type=int, help="user id: all linked characters and corps")
        who.add_argument("--character", type=int, help="one character id (character feeds only)")
        who.add_argument("--all", action="store_true", help="every account with a linked character")
        who.add_argument("--public", action="store_true", help="market prices and cost indices")
        parser.add_argument(
            "--feeds",
            help=f"comma-separated subset of {', '.join(f.value for f in Feed)} (default: all)",
        )

    def handle(self, *args, **options) -> None:
        feeds = None
        if options["feeds"]:
            try:
                feeds = {Feed(f.strip()) for f in options["feeds"].split(",") if f.strip()}
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        mode = "public" if options["public"] else f"accounts:{','.join(sorted(feeds or ['all']))}"
        with advisory_lock(_lock_key(mode)) as acquired:
            if not acquired:
                self.stdout.write(f"another sync_esi {mode} run is in progress; skipping")
                return
            self._run(options, feeds)

    def _run(self, options, feeds) -> None:
        if options["public"]:
            self.stdout.write(f"public: {sync.sync_public()}")
            return
        if options["character"]:
            ch = EveCharacter.objects.filter(pk=options["character"]).first()
            if ch is None:
                raise CommandError("unknown character")
            self._report(sync.sync_character(ch, feeds=feeds or sync.CHARACTER_FEEDS))
            return
        users = (
            User.objects.filter(pk=options["account"])
            if options["account"]
            else User.objects.filter(characters__esi_token__isnull=False).distinct()
        )
        if options["account"] and not users:
            raise CommandError("no matching account")
        for user in users:
            self.stdout.write(f"account {user.pk} ({user})")
            self._report(sync.sync_account(user, feeds=feeds))

    def _report(self, statuses) -> None:
        for s in statuses:
            source = f" via {s.source_character}" if s.source_character else ""
            outcome = f"{s.rows} rows" if s.ok else f"FAILED: {s.error}"
            self.stdout.write(f"  {s.owner_kind} {s.owner_id} {s.feed}{source}: {outcome}")
