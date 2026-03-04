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

def get_market_info(type_id: int) -> dict:
    """Get market info for a type ID, including price and volume."""
    db_entry = db.session.get(CachedMarketData, type_id)
    if db_entry and (db_entry.cached_at > datetime.now() - timedelta(hours=1)):
        return {"price": db_entry.price}
    url = f"https://esi.evetech.net/latest/markets/prices/?datasource=tranquility&market_group_id={type_id}"
    status, data = esi_get(url)
    if status == 200 and isinstance(data, list) and data:
        db_entry = CachedMarketData(type_id=type_id, price=data[0]['average_price'], cached_at=datetime.now())
        db.session.merge(db_entry)
        db.session.commit()
        return data[0]  # Return the first entry which should be the relevant one
    logger.warning("Failed to get market info for type_id %s: status %s", type_id, status)
    return {}
