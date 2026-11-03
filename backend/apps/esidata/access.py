"""Who may read corp data. Corp feeds are fetched with one director's token; an account may
read a corp's snapshot only if one of its own characters holds a role that ESI would require
for that feed in that corp. Viewers of shared plans never read these tables directly."""

from apps.accounts.models import User

from .models import CharacterRoles, Feed
from .sync import CORP_FEEDS


def readable_corp_feeds(user: User) -> dict[int, set[Feed]]:
    """corporation_id -> feeds this account may read."""
    out: dict[int, set[Feed]] = {}
    for r in CharacterRoles.objects.filter(character__user=user).select_related("character"):
        if r.corporation_id is None or r.corporation_id != r.character.corporation_id:
            continue  # roles are from a corp the character has since left
        for cf in CORP_FEEDS:
            if r.has(*cf.roles):
                out.setdefault(r.corporation_id, set()).add(cf.feed)
    return out
