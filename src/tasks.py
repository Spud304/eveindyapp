import base64
import logging
import os

from datetime import datetime, timezone, timedelta
from celery import shared_task

import requests

from src.models.models import db, User, CachedBlueprint, CachedSkill
from src.constants import ESI_BASE_URL
from src.utils import esi_get, resolve_location_names

logger = logging.getLogger(__name__)

TOKEN_REFRESH_WINDOW = timedelta(minutes=5)


@shared_task
def refresh_token_task(character_id):
    """Refresh a single user's ESI access token if it's near expiry."""
    user = db.session.get(User, character_id)
    if user is None:
        logger.warning("refresh_token_task: user %s not found", character_id)
        return {"character_id": character_id, "refreshed": False}

    now = datetime.now(timezone.utc)
    expires = user.access_token_expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires - now > TOKEN_REFRESH_WINDOW:
        return {"character_id": character_id, "refreshed": False}

    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    credentials = base64.urlsafe_b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()

    try:
        resp = requests.post(
            "https://login.eveonline.com/v2/oauth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": user.refresh_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_response = resp.json()
        user.update_token(token_response)
        user.token_refresh_failed = False
        db.session.commit()
        logger.info("Refreshed token for character %s", character_id)
        return {"character_id": character_id, "refreshed": True}
    except Exception:
        logger.warning(
            "Token refresh failed for character %s", character_id, exc_info=True
        )
        user.token_refresh_failed = True
        db.session.commit()
        return {"character_id": character_id, "refreshed": False}


@shared_task
def refresh_all_tokens_task():
    """Find all users with tokens expiring soon and dispatch refresh tasks."""
    from sqlalchemy import select

    threshold = datetime.now(timezone.utc) + TOKEN_REFRESH_WINDOW
    users = (
        db.session.execute(
            select(User.character_id).where(User.access_token_expires <= threshold)
        )
        .scalars()
        .all()
    )
    for cid in users:
        refresh_token_task.delay(cid)
    logger.info("Dispatched token refresh for %d users", len(users))
    return {"dispatched": len(users)}


def _ensure_fresh_token(character_id):
    """Ensure the user's token is fresh, refreshing synchronously if needed."""
    user = db.session.get(User, character_id)
    if user is None:
        return None

    now = datetime.now(timezone.utc)
    expires = user.access_token_expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires - now <= TOKEN_REFRESH_WINDOW:
        refresh_token_task(character_id)
        db.session.refresh(user)

    return user


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_skills_task(self, character_id):
    """Fetch and cache skills from ESI for a single character."""
    user = _ensure_fresh_token(character_id)
    if user is None:
        logger.warning("fetch_skills_task: user %s not found, skipping", character_id)
        return {"character_id": character_id, "error": "user_not_found"}

    headers = {
        "Authorization": f"Bearer {user.access_token}",
        "Content-Type": "application/json",
    }

    skills_url = f"{ESI_BASE_URL}/characters/{character_id}/skills"
    skills_status, skills_data = esi_get(skills_url, headers=headers)
    if skills_status != 200 or skills_data is None:
        raise self.retry(exc=Exception(f"Skills ESI returned {skills_status}"))

    now = datetime.now(timezone.utc)

    db.session.execute(
        CachedSkill.__table__.delete().where(CachedSkill.character_id == character_id)
    )
    skill_rows = [
        CachedSkill(
            character_id=character_id,
            skill_id=s["skill_id"],
            trained_skill_level=s["trained_skill_level"],
            active_skill_level=s["active_skill_level"],
            skillpoints_in_skill=s["skillpoints_in_skill"],
            cached_at=now,
        )
        for s in skills_data.get("skills", [])
    ]
    if skill_rows:
        db.session.add_all(skill_rows)
    db.session.commit()

    logger.info("Cached %d skills for character %s", len(skill_rows), character_id)
    return {"character_id": character_id, "skills_count": len(skill_rows)}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_blueprints_task(self, character_id):
    """Fetch blueprints from ESI, cache them, and resolve location names.

    Loads the user's current access token from DB, refreshing if needed.
    """
    user = _ensure_fresh_token(character_id)
    if user is None:
        raise self.retry(exc=Exception(f"User {character_id} not found"))

    access_token = user.access_token
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
    resolve_location_names(location_ids, headers, character_id)

    # --- Dispatch skill fetch for this character + all linked characters ---
    from sqlalchemy import select as sa_select

    linked_ids = (
        db.session.execute(
            sa_select(User.character_id).where(
                User.main_character_id == user.main_character_id
            )
        )
        .scalars()
        .all()
    )

    for cid in linked_ids:
        try:
            fetch_skills_task.delay(cid)
        except Exception:
            logger.warning(
                "Failed to dispatch skill fetch for character %s", cid, exc_info=True
            )

    return {
        "character_id": character_id,
        "count": len(all_bps),
        "skills_dispatched": len(linked_ids),
    }
