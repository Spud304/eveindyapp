import logging

from datetime import datetime, timezone
from celery import shared_task

from src.models.models import db, CachedBlueprint, CachedLocations
from src.constants import ESI_BASE_URL
from src.utils import esi_get

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_blueprints_task(self, character_id, access_token):
    """Fetch blueprints from ESI, cache them, and resolve location names.

    Runs as a Celery task outside of request context, so character_id and
    access_token are passed explicitly instead of using current_user.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # --- Fetch blueprints (paginated) ---
    url = f"{ESI_BASE_URL}/characters/{character_id}/blueprints"
    all_bps = []
    page = 1
    while True:
        status, data = esi_get(url, headers=headers, params={"page": page})
        if status != 200 or data is None:
            if page == 1:
                raise self.retry(exc=Exception(f"ESI returned {status} on page 1"))
            break
        all_bps.extend(data)
        if len(data) < 1000:
            break
        page += 1

    now = datetime.now(timezone.utc)

    # --- Cache blueprints ---
    db.session.execute(
        CachedBlueprint.__table__.delete().where(
            CachedBlueprint.character_id == character_id
        )
    )

    new_rows = [
        CachedBlueprint(
            character_id=character_id,
            item_id=bp["item_id"],
            type_id=bp["type_id"],
            location_id=bp["location_id"],
            location_flag=bp["location_flag"],
            quantity=bp["quantity"],
            runs=bp["runs"],
            material_efficiency=bp["material_efficiency"],
            time_efficiency=bp["time_efficiency"],
            cached_at=now,
        )
        for bp in all_bps
    ]
    if new_rows:
        db.session.add_all(new_rows)
    db.session.commit()

    # --- Resolve location names ---
    location_ids = {bp["location_id"] for bp in all_bps if bp.get("location_id")}
    _resolve_location_names(location_ids, headers, character_id)

    return {"character_id": character_id, "count": len(all_bps)}


def _resolve_location_names(location_ids, headers, character_id):
    """Resolve location IDs to names, caching results. Standalone version for task use."""
    if not location_ids:
        return

    from sqlalchemy import select

    cached = (
        db.session.execute(
            select(CachedLocations).where(
                CachedLocations.location_id.in_(location_ids)
            )
        )
        .scalars()
        .all()
    )
    known = {row.location_id for row in cached if row.location_name and row.location_name != "Unknown Location"}
    missing = location_ids - known

    if not missing:
        return

    asset_map = None
    for loc_id in missing:
        name = _fetch_location_name(loc_id, headers)
        if name is None or name == "Unknown Location":
            if asset_map is None:
                asset_map = _build_asset_location_map(headers, character_id)
            station_id = _follow_asset_chain(loc_id, asset_map)
            if station_id:
                resolved = _fetch_location_name(station_id, headers)
                if resolved and resolved != "Unknown Location":
                    name = resolved
            name = name or "Unknown Location"
        db.session.merge(CachedLocations(location_id=loc_id, location_name=name))

    db.session.commit()


def _fetch_location_name(location_id, headers):
    """Resolve a single location ID to a name via ESI."""
    if 60_000_000 <= location_id <= 63_999_999:
        url = f"{ESI_BASE_URL}/universe/stations/{location_id}/"
    elif location_id > 1_000_000_000_000:
        url = f"{ESI_BASE_URL}/universe/structures/{location_id}/"
    elif 30_000_000 <= location_id <= 39_999_999:
        url = f"{ESI_BASE_URL}/universe/systems/{location_id}/"
    else:
        return None

    status, data = esi_get(url, headers=headers)
    if status == 200 and data:
        return data.get("name", "Unknown Location")
    logger.warning("Failed to resolve location %s: status=%s", location_id, status)
    return "Unknown Location"


def _build_asset_location_map(headers, character_id):
    """Fetch character assets and return {item_id: location_id} map."""
    url = f"{ESI_BASE_URL}/characters/{character_id}/assets/"
    asset_map = {}
    page = 1
    while True:
        status, data = esi_get(url, headers=headers, params={"page": page})
        if status != 200 or not data:
            break
        for asset in data:
            asset_map[asset["item_id"]] = asset["location_id"]
        if len(data) < 1000:
            break
        page += 1
    return asset_map


def _follow_asset_chain(item_id, asset_map, max_depth=10):
    """Walk asset_map from item_id until we reach a station/structure ID."""
    current = item_id
    for _ in range(max_depth):
        parent = asset_map.get(current)
        if parent is None:
            return None
        if 60_000_000 <= parent <= 63_999_999:
            return parent
        if parent > 1_000_000_000_000:
            return parent
        current = parent
    return None
