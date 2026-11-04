import threading

import httpx
import pytest
from django.core.cache import cache
from django.db import connection, transaction

from apps.accounts import services, tokens
from apps.accounts.models import EveCharacter
from apps.accounts.sso import SsoIdentity
from apps.esi.client import EsiClient
from apps.esidata import access, sync
from apps.esidata.models import (
    Asset,
    BlueprintItem,
    CharacterRoles,
    CharacterSkill,
    CorpDivision,
    Feed,
    FeedStatus,
    IndustryJob,
    MarketPrice,
    OwnerKind,
    SystemCostIndex,
)

pytestmark = pytest.mark.django_db

MAIN, ALT, CORP, STATION, OFFICE = 90000001, 90000002, 98000001, 60003760, 1000000000001
ALL_SCOPES = tuple(sync.SCOPE.values()) + ("publicData",)


def job(job_id, **kw):
    row = {
        "job_id": job_id,
        "installer_id": MAIN,
        "facility_id": STATION,
        "activity_id": 1,
        "blueprint_id": 5,
        "blueprint_type_id": 691,
        "blueprint_location_id": STATION,
        "output_location_id": STATION,
        "runs": 10,
        "status": "active",
        "duration": 3600,
        "start_date": "2026-11-03T10:00:00Z",
        "end_date": "2026-11-03T11:00:00Z",
    }
    row.update(kw)
    return row


class FakeEsi:
    """Routes keyed by path; values are bodies, or (status, body), or a list of pages."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((path, request.headers.get("Authorization")))
        if path not in self.routes:
            return httpx.Response(404, json={"error": "not found"})
        value = self.routes[path]
        if isinstance(value, tuple):
            return httpx.Response(value[0], json=value[1])
        if isinstance(value, Pages):
            page = int(request.url.params.get("page", 1))
            body = value.pages[page - 1]
            headers = {"X-Pages": str(len(value.pages))}
            if isinstance(body, tuple):  # (status, body): this page fails
                return httpx.Response(body[0], json=body[1], headers=headers)
            return httpx.Response(200, json=body, headers=headers)
        return httpx.Response(200, json=value)


class Pages:
    def __init__(self, *pages):
        self.pages = pages


def character_routes(cid=MAIN):
    return {
        f"/characters/{cid}/skills/": {
            "skills": [
                {
                    "skill_id": 3380,
                    "active_skill_level": 5,
                    "trained_skill_level": 5,
                    "skillpoints_in_skill": 256000,
                }
            ],
            "total_sp": 256000,
        },
        f"/characters/{cid}/roles/": {"roles": ["Director", "Factory_Manager"]},
        f"/characters/{cid}/assets/": Pages(
            [
                # a container in the station hangar, with Tritanium inside it
                {
                    "item_id": 10,
                    "type_id": 3465,
                    "quantity": 1,
                    "location_id": STATION,
                    "location_type": "station",
                    "location_flag": "Hangar",
                    "is_singleton": True,
                },
                {
                    "item_id": 11,
                    "type_id": 34,
                    "quantity": 5000,
                    "location_id": 10,
                    "location_type": "item",
                    "location_flag": "Unlocked",
                    "is_singleton": False,
                },
            ],
            [
                {
                    "item_id": 12,
                    "type_id": 35,
                    "quantity": 100,
                    "location_id": STATION,
                    "location_type": "station",
                    "location_flag": "Hangar",
                    "is_singleton": False,
                },
            ],
        ),
        f"/characters/{cid}/blueprints/": Pages(
            [
                {
                    "item_id": 20,
                    "type_id": 691,
                    "location_id": 10,
                    "location_flag": "Unlocked",
                    "quantity": -1,
                    "runs": -1,
                    "material_efficiency": 10,
                    "time_efficiency": 20,
                },
                {
                    "item_id": 21,
                    "type_id": 691,
                    "location_id": STATION,
                    "location_flag": "Hangar",
                    "quantity": -2,
                    "runs": 5,
                    "material_efficiency": 8,
                    "time_efficiency": 16,
                },
            ]
        ),
        f"/characters/{cid}/industry/jobs/": [
            job(1, station_id=STATION),
            job(2, station_id=STATION, status="delivered"),
        ],
    }


def corp_routes():
    return {
        f"/corporations/{CORP}/": {"name": "Test Corp", "ticker": "TEST"},
        f"/corporations/{CORP}/assets/": Pages(
            [
                {
                    "item_id": OFFICE,
                    "type_id": 27,
                    "quantity": 1,
                    "location_id": STATION,
                    "location_type": "station",
                    "location_flag": "OfficeFolder",
                    "is_singleton": True,
                },
                {
                    "item_id": 30,
                    "type_id": 34,
                    "quantity": 1_000_000,
                    "location_id": OFFICE,
                    "location_type": "item",
                    "location_flag": "CorpSAG3",
                    "is_singleton": False,
                },
            ]
        ),
        f"/corporations/{CORP}/blueprints/": Pages(
            [
                {
                    "item_id": 40,
                    "type_id": 691,
                    "location_id": OFFICE,
                    "location_flag": "CorpSAG2",
                    "quantity": 3,
                    "runs": -1,
                    "material_efficiency": 0,
                    "time_efficiency": 0,
                }
            ]
        ),
        f"/corporations/{CORP}/industry/jobs/": Pages([job(3, location_id=STATION)]),
        f"/corporations/{CORP}/divisions/": {
            "hangar": [{"division": 1, "name": "Main"}, {"division": 3, "name": "Minerals"}]
        },
    }


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch):
    cache.clear()
    monkeypatch.setattr(tokens, "access_token", lambda ch, *scopes: f"tok-{getattr(ch, 'pk', ch)}")
    yield
    cache.clear()


def linked(cid=MAIN, name="Main", corp=CORP, scopes=ALL_SCOPES, user=None):
    ch = services.upsert_character(SsoIdentity(cid, name, "o", ()), {"corporation_id": corp})
    user = user or services.ensure_user(ch)
    services.link_character(user, ch)
    services.store_tokens(ch, {"access_token": "a", "refresh_token": "r"}, scopes)
    return EveCharacter.objects.get(pk=cid)


def client(routes):
    fake = FakeEsi(routes)
    return EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(fake)), fake


# --- location resolution --------------------------------------------------------------------


def test_resolve_locations_walks_containers_and_offices():
    rows = [
        {"item_id": OFFICE, "location_id": STATION, "location_flag": "OfficeFolder"},
        {"item_id": 2, "location_id": OFFICE, "location_flag": "CorpSAG4"},
        {"item_id": 3, "location_id": 2, "location_flag": "Unlocked"},  # inside a container
        {"item_id": 4, "location_id": 30000142, "location_flag": "Hangar"},
    ]
    where = sync.resolve_locations(rows)
    assert where[3] == (STATION, "CorpSAG4")
    assert where[2] == (STATION, "CorpSAG4")
    assert where[4] == (30000142, "Hangar")


def test_resolve_locations_survives_a_cycle():
    rows = [
        {"item_id": 1, "location_id": 2, "location_flag": "Cargo"},
        {"item_id": 2, "location_id": 1, "location_flag": "Cargo"},
    ]
    assert set(sync.resolve_locations(rows)) == {1, 2}


# --- character feeds -------------------------------------------------------------------------


def test_sync_character_writes_every_feed():
    ch = linked()
    c, fake = client(character_routes())
    statuses = sync.sync_character(ch, client=c)
    assert all(s.ok for s in statuses), [s.error for s in statuses]
    assert CharacterSkill.objects.get(character=ch).active_level == 5
    assert CharacterRoles.objects.get(character=ch).has("Director")
    trit = Asset.objects.get(item_id=11)
    assert (trit.root_location_id, trit.hangar_flag) == (STATION, "Hangar")
    assert (
        Asset.objects.filter(owner_kind=OwnerKind.CHARACTER, owner_id=MAIN).count() == 3
    )  # 2 pages
    bpo = BlueprintItem.objects.get(item_id=20)
    assert bpo.root_location_id == STATION and not bpo.is_copy and bpo.material_efficiency == 10
    assert BlueprintItem.objects.get(item_id=21).is_copy
    assert IndustryJob.objects.filter(owner_id=MAIN).count() == 2
    assert all(auth == f"Bearer tok-{MAIN}" for path, auth in fake.calls)


def test_resync_replaces_assets_and_keeps_old_jobs():
    ch = linked()
    routes = character_routes()
    sync.sync_character(ch, client=client(routes)[0])
    routes[f"/characters/{MAIN}/assets/"] = Pages([])
    routes[f"/characters/{MAIN}/industry/jobs/"] = [job(1, station_id=STATION, status="ready")]
    cache.clear()  # drop ETag cache so the new bodies are read
    sync.sync_character(ch, client=client(routes)[0])
    assert not Asset.objects.filter(owner_id=MAIN).exists()
    assert IndustryJob.objects.get(pk=1).status == "ready"
    assert IndustryJob.objects.filter(pk=2).exists()  # dropped by ESI, kept here


def test_failed_resync_keeps_the_previous_assets():
    ch = linked()
    routes = character_routes()
    sync.sync_character(ch, client=client(routes)[0])
    before = set(Asset.objects.filter(owner_id=MAIN).values_list("item_id", "quantity"))
    assert before
    routes[f"/characters/{MAIN}/assets/"] = (500, {"error": "boom"})
    cache.clear()
    statuses = {s.feed: s for s in sync.sync_character(ch, client=client(routes)[0])}
    assert not statuses[Feed.ASSETS].ok and "500" in statuses[Feed.ASSETS].error
    assert set(Asset.objects.filter(owner_id=MAIN).values_list("item_id", "quantity")) == before


def test_corp_resync_failing_on_a_later_page_keeps_every_previous_row():
    main = linked()
    routes = {**character_routes(), **corp_routes()}
    c, _ = client(routes)
    sync.sync_character(main, client=c)
    sync.sync_corporation(CORP, client=c)
    corp_rows = Asset.objects.filter(owner_kind=OwnerKind.CORPORATION, owner_id=CORP)
    before = set(corp_rows.values_list("item_id", "quantity"))
    first_page = routes[f"/corporations/{CORP}/assets/"].pages[0]
    routes[f"/corporations/{CORP}/assets/"] = Pages(first_page, (503, {"error": "busy"}))
    cache.clear()
    statuses = {s.feed: s for s in sync.sync_corporation(CORP, client=client(routes)[0])}
    assert not statuses[Feed.ASSETS].ok
    assert set(corp_rows.values_list("item_id", "quantity")) == before  # no half snapshot


def test_failed_feed_is_recorded_and_others_still_run():
    ch = linked()
    routes = character_routes()
    routes[f"/characters/{MAIN}/assets/"] = (403, {"error": "token not valid for scope"})
    statuses = {s.feed: s for s in sync.sync_character(ch, client=client(routes)[0])}
    assert not statuses[Feed.ASSETS].ok and "403" in statuses[Feed.ASSETS].error
    assert statuses[Feed.SKILLS].ok and statuses[Feed.JOBS].ok
    status = FeedStatus.objects.get(owner_id=MAIN, feed=Feed.ASSETS)
    assert status.fetched_at is None and status.attempted_at is not None


ASSET_ROWS = [
    {
        "item_id": i,
        "type_id": 34,
        "quantity": 100,
        "location_id": STATION,
        "location_type": "station",
        "location_flag": "Hangar",
        "is_singleton": False,
    }
    for i in range(1, 6)
]


@pytest.mark.django_db(transaction=True)
def test_overlapping_snapshot_writes_do_not_duplicate_rows():
    """A "refresh now" sync writing an owner's assets while the cron sync's write is still
    open: the second waits for the first and replaces its rows. Without the lock, the second
    DELETE cannot see the first one's uncommitted rows and both inserts survive."""
    errors = []

    def second():
        try:
            sync._write_assets(OwnerKind.CORPORATION, CORP, ASSET_ROWS)
        except Exception as exc:  # noqa: BLE001 - reported through the assertion below
            errors.append(exc)
        finally:
            connection.close()

    with transaction.atomic():
        sync._write_assets(OwnerKind.CORPORATION, CORP, ASSET_ROWS)
        t = threading.Thread(target=second)
        t.start()
        t.join(timeout=1.0)
        assert t.is_alive(), "the second writer should wait for the first transaction"
    t.join()
    assert errors == []
    assert Asset.objects.filter(owner_kind=OwnerKind.CORPORATION, owner_id=CORP).count() == 5


def test_snapshot_repeating_an_item_id_fails_the_feed_and_keeps_old_rows():
    sync._write_assets(OwnerKind.CORPORATION, CORP, ASSET_ROWS)
    repeated = ASSET_ROWS + [{**ASSET_ROWS[0], "quantity": 1}]
    status = sync._record(
        OwnerKind.CORPORATION,
        CORP,
        Feed.ASSETS,
        lambda: sync._write_assets(OwnerKind.CORPORATION, CORP, repeated),
    )
    assert not status.ok and "esidata_asset_owner_item" in status.error
    assert Asset.objects.filter(owner_kind=OwnerKind.CORPORATION, owner_id=CORP).count() == 5


def test_sso_outage_is_a_feed_error_and_the_account_sync_goes_on(monkeypatch):
    main = linked()
    alt = linked(ALT, "Alt", user=main.user)

    def down(character, *scopes):
        if getattr(character, "pk", character) == MAIN:
            raise tokens.TokenRefreshFailed("character 90000001: token refresh failed: HTTP 502")
        return "tok"

    monkeypatch.setattr(tokens, "access_token", down)
    routes = {**character_routes(MAIN), **character_routes(ALT)}
    sync.sync_account(main.user, client=client(routes)[0])
    failed = FeedStatus.objects.get(owner_id=MAIN, feed=Feed.SKILLS)
    assert not failed.ok and "HTTP 502" in failed.error
    assert FeedStatus.objects.get(owner_id=alt.pk, feed=Feed.SKILLS).ok


def test_missing_token_is_a_feed_error(monkeypatch):
    ch = linked()

    def no_token(character, *scopes):
        raise tokens.TokenUnavailable("character lacks scopes")

    monkeypatch.setattr(tokens, "access_token", no_token)
    statuses = sync.sync_character(ch, feeds=(Feed.SKILLS,), client=client({})[0])
    assert not statuses[0].ok and "lacks scopes" in statuses[0].error


# --- corp feeds ------------------------------------------------------------------------------


def test_corp_sync_uses_director_and_resolves_divisions():
    main = linked()
    c, _ = client({**character_routes(), **corp_routes()})
    sync.sync_character(main, client=c)
    statuses = {s.feed: s for s in sync.sync_corporation(CORP, client=c)}
    assert all(s.ok for s in statuses.values()), {f: s.error for f, s in statuses.items()}
    assert statuses[Feed.ASSETS].source_character_id == MAIN
    trit = Asset.objects.get(owner_kind=OwnerKind.CORPORATION, item_id=30)
    assert (trit.root_location_id, trit.hangar_flag) == (STATION, "CorpSAG3")
    stack = BlueprintItem.objects.get(item_id=40)
    assert stack.quantity == 3 and stack.hangar_flag == "CorpSAG2"
    assert dict(CorpDivision.objects.values_list("division", "name")) == {1: "Main", 3: "Minerals"}
    assert IndustryJob.objects.get(pk=3).location_id == STATION


def test_corp_feed_needs_the_role():
    main = linked()
    CharacterRoles.objects.create(character=main, corporation_id=CORP, roles=["Factory_Manager"])
    statuses = {s.feed: s for s in sync.sync_corporation(CORP, client=client(corp_routes())[0])}
    assert not statuses[Feed.ASSETS].ok and "Director" in statuses[Feed.ASSETS].error
    assert statuses[Feed.JOBS].ok and statuses[Feed.JOBS].source_character_id == MAIN


def test_corp_source_skips_missing_scope_and_stale_roles():
    main = linked()
    alt = linked(ALT, "Alt", scopes=("publicData",), user=main.user)
    CharacterRoles.objects.create(character=alt, corporation_id=CORP, roles=["Director"])
    CharacterRoles.objects.create(
        character=main, corporation_id=999, roles=["Director"]
    )  # old corp
    with pytest.raises(sync.FeedUnavailable):
        sync.corp_source(CORP, sync.CORP_FEEDS[0])
    CharacterRoles.objects.filter(character=main).update(corporation_id=CORP)
    assert sync.corp_source(CORP, sync.CORP_FEEDS[0]) == main


def test_sync_account_runs_characters_then_corps():
    main = linked()
    routes = {
        **character_routes(),
        **corp_routes(),
        "/characters/affiliation/": [{"character_id": MAIN, "corporation_id": CORP}],
    }
    statuses = sync.sync_account(main.user, client=client(routes)[0])
    kinds = [s.owner_kind for s in statuses]
    assert kinds.index(OwnerKind.CORPORATION) > kinds.index(OwnerKind.CHARACTER)
    assert all(s.ok for s in statuses), [(s.feed, s.error) for s in statuses if not s.ok]


# --- public data and access ------------------------------------------------------------------


def test_sync_public_prices_and_cost_indices():
    routes = {
        "/markets/prices/": [
            {"type_id": 34, "adjusted_price": 4.1, "average_price": 4.0},
            {"type_id": 35},
        ],
        "/industry/systems/": [
            {
                "solar_system_id": 30000142,
                "cost_indices": [{"activity": "manufacturing", "cost_index": 0.05}],
            }
        ],
    }
    assert sync.sync_public(client(routes)[0]) == {"prices": 2, "cost_indices": 1}
    assert MarketPrice.objects.get(pk=34).adjusted_price == 4.1
    assert MarketPrice.objects.get(pk=35).adjusted_price is None
    assert SystemCostIndex.objects.get(system_id=30000142).cost_index == 0.05


def test_corp_data_readable_only_with_role_in_that_corp():
    main = linked()
    CharacterRoles.objects.create(character=main, corporation_id=CORP, roles=["Factory_Manager"])
    assert access.readable_corp_feeds(main.user) == {CORP: {Feed.JOBS}}
    CharacterRoles.objects.filter(character=main).update(roles=["Director"])
    assert access.readable_corp_feeds(main.user)[CORP] == {
        Feed.ASSETS,
        Feed.BLUEPRINTS,
        Feed.DIVISIONS,
        Feed.JOBS,
    }
    EveCharacter.objects.filter(pk=MAIN).update(corporation_id=555)  # left the corp
    assert access.readable_corp_feeds(main.user) == {}


def test_corp_access_ends_when_the_token_does():
    from django.utils import timezone

    from apps.accounts.models import EsiToken

    main = linked()
    CharacterRoles.objects.create(character=main, corporation_id=CORP, roles=["Director"])
    assert CORP in access.readable_corp_feeds(main.user)
    EsiToken.objects.filter(pk=MAIN).update(refresh_failed_at=timezone.now())  # revoked
    assert access.readable_corp_feeds(main.user) == {}
    EsiToken.objects.filter(pk=MAIN).delete()  # transferred or unlinked
    assert access.readable_corp_feeds(main.user) == {}
