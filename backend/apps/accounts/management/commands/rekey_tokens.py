"""Re-encrypt every stored ESI token with the current key.

Use it after setting `TOKEN_ENCRYPTION_KEY` (or changing `SECRET_KEY`): pass the `SECRET_KEY`
the tokens were encrypted under (or `--old-key`, a Fernet key), and every token is decrypted
with that and encrypted again with the current settings, in one transaction. Nothing is
written unless every token decrypts.

    uv run python manage.py rekey_tokens --old-secret-key dev-insecure-secret-key --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts import crypto
from apps.accounts.models import EsiToken


class Command(BaseCommand):
    help = "Re-encrypt stored ESI tokens with the current TOKEN_ENCRYPTION_KEY / SECRET_KEY."

    def add_arguments(self, parser: CommandParser) -> None:
        old = parser.add_mutually_exclusive_group(required=True)
        old.add_argument("--old-secret-key", help="SECRET_KEY the tokens were encrypted under")
        old.add_argument("--old-key", help="TOKEN_ENCRYPTION_KEY the tokens were encrypted under")
        parser.add_argument("--dry-run", action="store_true", help="check, write nothing")

    def handle(self, *args, **opts) -> None:
        old = crypto._fernet(opts["old_key"] or "", opts["old_secret_key"] or "")
        new = crypto.fernet()
        if not settings.TOKEN_ENCRYPTION_KEY:
            self.stderr.write(
                "TOKEN_ENCRYPTION_KEY is not set: the new key is derived from SECRET_KEY."
            )
        with transaction.atomic():
            tokens = list(EsiToken.objects.select_for_update())
            changed = 0
            for t in tokens:
                for field in ("refresh_token", "access_token"):
                    value = getattr(t, field)
                    if not value:
                        continue
                    try:
                        plain = old.decrypt(value.encode())
                    except Exception as exc:  # noqa: BLE001 - InvalidToken and malformed values
                        raise CommandError(
                            f"character {t.character_id} {field} does not decrypt with the old "
                            "key; nothing was changed"
                        ) from exc
                    setattr(t, field, new.encrypt(plain).decode())
                changed += 1
            if opts["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(f"{changed} token(s) decrypt with the old key; nothing written")
                return
            for t in tokens:
                t.save(update_fields=["refresh_token", "access_token"])
        self.stdout.write(f"re-encrypted {changed} token(s)")
