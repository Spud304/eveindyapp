import pytest
from django.core.management import call_command

from apps.accounts import services
from apps.accounts.models import EveCharacter, User
from apps.accounts.sso import SsoIdentity
from apps.planning.models import Plan

pytestmark = pytest.mark.django_db


def account(character_id: int) -> User:
    ch = services.upsert_character(SsoIdentity(character_id, f"c{character_id}", "o", ()), {})
    user = services.ensure_user(ch)
    Plan.objects.create(user=user, name="p")
    return user


def test_deletes_only_the_reserved_test_range():
    real = account(2118813889)
    edge_low, edge_high = account(900_000_000), account(900_000_100)  # just outside
    account(900_000_001)
    account(900_000_099)
    call_command("playwright_cleanup")
    left = set(EveCharacter.objects.values_list("character_id", flat=True))
    assert left == {2118813889, 900_000_000, 900_000_100}
    assert set(User.objects.values_list("pk", flat=True)) == {real.pk, edge_low.pk, edge_high.pk}
    assert Plan.objects.count() == 3
