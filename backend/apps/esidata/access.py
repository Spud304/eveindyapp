"""Who may read corp data. Corp feeds are fetched with one director's token; an account may
read a corp's snapshot only if one of its own characters holds a role that ESI would require
for that feed in that corp. Viewers of shared plans never read these tables directly."""

from apps.accounts.models import User

from .models import CharacterRoles, Feed
from .sync import CORP_FEEDS


def readable_corp_feeds(user: User) -> dict[int, set[Feed]]:
    """corporation_id -> feeds this account may read."""
    out: dict[int, set[Feed]] = {}
    # Only characters with a working token count: a revoked or rejected token, or a transfer
    # (which drops the token), ends access instead of leaving the last roles in force.
    rows = CharacterRoles.objects.filter(
        character__user=user,
        character__esi_token__isnull=False,
        character__esi_token__refresh_failed_at__isnull=True,
    ).select_related("character")
    for r in rows:
        if r.corporation_id is None or r.corporation_id != r.character.corporation_id:
            continue  # roles are from a corp the character has since left
        for cf in CORP_FEEDS:
            if r.has(*cf.roles):
                out.setdefault(r.corporation_id, set()).add(cf.feed)
    return out


def owner_q(user: User, feed: Feed):
    """Rows of a feed this account may read: its characters', plus each corp where one of its
    characters holds the feed's role."""
    from django.db.models import Q

    from .models import OwnerKind

    q = Q(owner_kind=OwnerKind.CHARACTER, owner_id__in=user.characters.values("character_id"))
    for corp_id, feeds in readable_corp_feeds(user).items():
        if feed in feeds:
            q |= Q(owner_kind=OwnerKind.CORPORATION, owner_id=corp_id)
    return q
