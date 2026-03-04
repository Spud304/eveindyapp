import logging
import random
import hmac
import hashlib
import requests

from flask import current_app
from flask_login import current_user
from sqlalchemy import select
from datetime import datetime, timedelta

from src.models.models import db, InvTypes, CachedMarketData

logger = logging.getLogger(__name__)


def generate_token():
    """Generates a non-guessable OAuth token"""
    chars = ('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    rand = random.SystemRandom()
    random_string = ''.join(rand.choice(chars) for _ in range(40))
    return hmac.new(
        current_app.config['SECRET_KEY'].encode('utf-8'),
        random_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def esi_headers() -> dict:
    """Return ESI API auth headers for the currently authenticated user."""
    token = current_user.get_sso_data()['access_token']
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
        select(InvTypes.typeID, InvTypes.typeName).where(InvTypes.typeID.in_(type_ids))
    ).all()
    return {r.typeID: r.typeName for r in rows}

def batch_market_info(type_ids: set[int]) -> dict[int, float]:
    """Get prices for multiple type IDs. Returns {type_id: price}.

    Checks cache first, then fetches all prices from ESI in a single call
    for any that are missing or stale.
    """
    if not type_ids:
        return {}

    cutoff = datetime.now() - timedelta(hours=1)
    result = {}

    # Check cache for all requested type_ids
    cached = db.session.execute(
        select(CachedMarketData).where(CachedMarketData.type_id.in_(type_ids))
    ).scalars().all()

    stale_or_missing = set(type_ids)
    for entry in cached:
        if entry.cached_at > cutoff:
            result[entry.type_id] = entry.price
            stale_or_missing.discard(entry.type_id)

    if not stale_or_missing:
        return result

    # Single ESI call returns all market prices
    url = "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility"
    status, data = esi_get(url)
    if status != 200 or not isinstance(data, list):
        logger.warning("Failed to fetch market prices: status %s", status)
        return result

    now = datetime.now()
    prices_by_type = {item['type_id']: item.get('average_price', 0) for item in data}

    for tid in stale_or_missing:
        price = prices_by_type.get(tid)
        if price is not None:
            result[tid] = price
            db.session.merge(CachedMarketData(type_id=tid, price=price, cached_at=now))

    db.session.commit()
    return result
