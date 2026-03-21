import logging
import random
import hmac
import hashlib
import requests

from flask import current_app
from flask_login import current_user
from sqlalchemy import select
from datetime import datetime, timedelta

from src.models.models import db, EveType, CachedMarketData, CachedLocations

logger = logging.getLogger(__name__)


def generate_token():
    """Generates a non-guessable OAuth token"""
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    rand = random.SystemRandom()
    random_string = "".join(rand.choice(chars) for _ in range(40))
    return hmac.new(
        current_app.config["SECRET_KEY"].encode("utf-8"),
        random_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def esi_headers() -> dict:
    """Return ESI API auth headers for the currently authenticated user."""
    token = current_user.get_sso_data()["access_token"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def esi_get(url: str, headers: dict = None, **kwargs):
    """GET from ESI with timeout. Returns (status_code, json_or_None)."""
    if headers is None:
        headers = esi_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=10, **kwargs)
        return resp.status_code, resp.json() if resp.text else None
    except requests.RequestException as e:
        logger.warning("ESI request failed: %s — %s", url, e)
        return 0, None


def esi_post(url: str, headers: dict = None, **kwargs):
    """POST to ESI with timeout. Returns (status_code, json_or_None)."""
    if headers is None:
        headers = esi_headers()
    try:
        resp = requests.post(url, headers=headers, timeout=10, **kwargs)
        return resp.status_code, resp.json() if resp.text else None
    except requests.RequestException as e:
        logger.warning("ESI request failed: %s — %s", url, e)
        return 0, None


def batch_type_names(type_ids: set[int]) -> dict[int, str]:
    """Resolve a set of type IDs to their names in a single query."""
    if not type_ids:
        return {}
    rows = db.session.execute(
        select(EveType.typeID, EveType.typeName).where(EveType.typeID.in_(type_ids))
    ).all()
    return {r.typeID: r.typeName for r in rows}


def batch_market_info(type_ids: set[int]) -> tuple[dict[int, float], dict[int, float]]:
    """Get prices for multiple type IDs.

    Returns (average_prices, adjusted_prices) — both {type_id: price}.
    Checks cache first, then fetches all prices from ESI in a single call
    for any that are missing or stale.
    """
    if not type_ids:
        return {}, {}

    cutoff = datetime.now() - timedelta(hours=1)
    avg_result = {}
    adj_result = {}

    # Check cache for all requested type_ids
    cached = (
        db.session.execute(
            select(CachedMarketData).where(CachedMarketData.type_id.in_(type_ids))
        )
        .scalars()
        .all()
    )

    stale_or_missing = set(type_ids)
    for entry in cached:
        if entry.cached_at > cutoff:
            avg_result[entry.type_id] = entry.price
            if entry.adjusted_price is not None:
                adj_result[entry.type_id] = entry.adjusted_price
            stale_or_missing.discard(entry.type_id)

    if not stale_or_missing:
        return avg_result, adj_result

    # Single ESI call returns all market prices
    url = "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility"
    status, data = esi_get(url, headers={"Content-Type": "application/json"})
    if status != 200 or not isinstance(data, list):
        logger.warning("Failed to fetch market prices: status %s", status)
        return avg_result, adj_result

    now = datetime.now()
    esi_by_type = {item["type_id"]: item for item in data}

    for tid in stale_or_missing:
        item = esi_by_type.get(tid)
        if item is not None:
            avg_price = item.get("average_price", 0)
            adj_price = item.get("adjusted_price", 0)
            avg_result[tid] = avg_price
            adj_result[tid] = adj_price
            db.session.merge(
                CachedMarketData(
                    type_id=tid,
                    price=avg_price,
                    adjusted_price=adj_price,
                    cached_at=now,
                )
            )

    db.session.commit()
    return avg_result, adj_result


def search_systems(query: str, limit: int = 15) -> list[dict]:
    """Search solar systems by name prefix. Returns list of {system_id, name} dicts."""
    from src.models.models import MapSolarSystem

    if len(query) < 2:
        return []
    results = db.session.execute(
        select(MapSolarSystem.solarSystemID, MapSolarSystem.solarSystemName)
        .where(MapSolarSystem.solarSystemName.ilike(f"%{query}%"))
        .limit(limit)
    ).all()
    return [{"system_id": r.solarSystemID, "name": r.solarSystemName} for r in results]


def resolve_location_names(location_ids, headers, character_id):
    """Resolve location IDs to names, caching results. Standalone version for use without Flask request context."""
    if not location_ids:
        return

    cached = (
        db.session.execute(
            select(CachedLocations).where(CachedLocations.location_id.in_(location_ids))
        )
        .scalars()
        .all()
    )
    known = {
        row.location_id
        for row in cached
        if row.location_name and row.location_name != "Unknown Location"
    }
    missing = location_ids - known

    if not missing:
        return

    asset_map = None
    for loc_id in missing:
        name = fetch_location_name(loc_id, headers)
        if name is None or name == "Unknown Location":
            if asset_map is None:
                asset_map = build_asset_location_map(headers, character_id)
            station_id = follow_asset_chain(loc_id, asset_map)
            if station_id:
                resolved = fetch_location_name(station_id, headers)
                if resolved and resolved != "Unknown Location":
                    name = resolved
            name = name or "Unknown Location"
        db.session.merge(CachedLocations(location_id=loc_id, location_name=name))

    db.session.commit()


def fetch_location_name(location_id, headers):
    """Resolve a single location ID to a name via ESI."""
    from src.constants import (
        ESI_BASE_URL,
        STATION_ID_RANGE,
        STRUCTURE_ID_MIN,
        SYSTEM_ID_RANGE,
    )

    if STATION_ID_RANGE[0] <= location_id <= STATION_ID_RANGE[1]:
        url = f"{ESI_BASE_URL}/universe/stations/{location_id}/"
    elif location_id > STRUCTURE_ID_MIN:
        url = f"{ESI_BASE_URL}/universe/structures/{location_id}/"
    elif SYSTEM_ID_RANGE[0] <= location_id <= SYSTEM_ID_RANGE[1]:
        url = f"{ESI_BASE_URL}/universe/systems/{location_id}/"
    else:
        return None

    status, data = esi_get(url, headers=headers)
    if status == 200 and data:
        return data.get("name", "Unknown Location")
    logger.warning("Failed to resolve location %s: status=%s", location_id, status)
    return "Unknown Location"


def build_asset_location_map(headers, character_id):
    """Fetch character assets and return {item_id: location_id} map."""
    from src.constants import ESI_BASE_URL

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


def follow_asset_chain(item_id, asset_map, max_depth=10):
    """Walk asset_map from item_id until we reach a station/structure ID."""
    from src.constants import STATION_ID_RANGE, STRUCTURE_ID_MIN

    current = item_id
    for _ in range(max_depth):
        parent = asset_map.get(current)
        if parent is None:
            return None
        if STATION_ID_RANGE[0] <= parent <= STATION_ID_RANGE[1]:
            return parent
        if parent > STRUCTURE_ID_MIN:
            return parent
        current = parent
    return None


def get_manufacturing_cost_index(system_id: int) -> float:
    """Fetch the manufacturing cost index for a solar system from ESI.

    Uses CachedLocations to avoid repeated calls. Returns 0.0 if not found.
    """
    cached = db.session.get(CachedLocations, system_id)
    if cached and cached.location_cost_index is not None:
        if (
            cached.location_cost_index_last_updated
            and cached.location_cost_index_last_updated
            > datetime.now() - timedelta(hours=12)
        ):
            return cached.location_cost_index

    url = "https://esi.evetech.net/latest/industry/systems/?datasource=tranquility"
    status, data = esi_get(url, headers={"Content-Type": "application/json"})
    if status != 200 or not isinstance(data, list):
        logger.warning("Failed to fetch industry systems: status %s", status)
        return (
            cached.location_cost_index
            if cached and cached.location_cost_index is not None
            else 0.0
        )

    cost_index = 0.0
    for system in data:
        if system.get("solar_system_id") == system_id:
            for activity in system.get("cost_indices", []):
                if activity.get("activity") == "manufacturing":
                    cost_index = activity.get("cost_index", 0.0)
                    break
            break

    now = datetime.now()
    if cached:
        cached.location_cost_index = cost_index
        cached.location_cost_index_last_updated = now
    else:
        db.session.add(
            CachedLocations(
                location_id=system_id,
                location_name="",
                location_cost_index=cost_index,
                location_cost_index_last_updated=now,
            )
        )
    db.session.commit()
    return cost_index
