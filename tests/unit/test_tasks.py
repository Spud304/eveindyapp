import pytest
import responses
from datetime import datetime, timezone

from src.models.models import db, CachedBlueprint, CachedSkill

ESI_BASE = "https://esi.evetech.net/latest"


def _mock_blueprints(character_id, bps=None):
    """Register a mock for the blueprints ESI endpoint."""
    responses.add(
        responses.GET,
        f"{ESI_BASE}/characters/{character_id}/blueprints",
        json=bps or [],
        status=200,
    )


def _mock_skills(character_id, skills=None, status=200):
    """Register a mock for the skills ESI endpoint."""
    body = {"skills": skills or [], "total_sp": 0, "unallocated_sp": 0}
    responses.add(
        responses.GET,
        f"{ESI_BASE}/characters/{character_id}/skills",
        json=body,
        status=status,
    )


SAMPLE_SKILLS = [
    {
        "skill_id": 3380,
        "trained_skill_level": 5,
        "active_skill_level": 5,
        "skillpoints_in_skill": 256000,
    },
    {
        "skill_id": 3388,
        "trained_skill_level": 4,
        "active_skill_level": 3,
        "skillpoints_in_skill": 45255,
    },
]


class TestFetchSkillsTask:
    """Test the standalone fetch_skills_task."""

    @pytest.fixture(autouse=True)
    def _clean_skills(self, app):
        """Remove cached skills before each test."""
        with app.app_context():
            db.session.execute(CachedSkill.__table__.delete())
            db.session.commit()
        yield

    @responses.activate
    def test_skills_cached_on_success(self, app, test_user):
        """Skills are cached when ESI returns 200."""
        from src.tasks import fetch_skills_task

        cid = test_user.character_id
        _mock_skills(cid, SAMPLE_SKILLS)

        with app.app_context():
            result = fetch_skills_task(cid)

        with app.app_context():
            rows = db.session.query(CachedSkill).filter_by(character_id=cid).all()
            assert len(rows) == 2
            assert result["skills_count"] == 2

            by_id = {r.skill_id: r for r in rows}
            assert by_id[3380].trained_skill_level == 5
            assert by_id[3388].active_skill_level == 3

    @responses.activate
    def test_skills_replaces_old_cache(self, app, test_user):
        """Old cached skills are cleared before inserting new ones."""
        cid = test_user.character_id

        with app.app_context():
            old = CachedSkill(
                character_id=cid,
                skill_id=9999,
                trained_skill_level=1,
                active_skill_level=1,
                skillpoints_in_skill=100,
                cached_at=datetime.now(timezone.utc),
            )
            db.session.add(old)
            db.session.commit()

        from src.tasks import fetch_skills_task

        _mock_skills(cid, SAMPLE_SKILLS)

        with app.app_context():
            fetch_skills_task(cid)

        with app.app_context():
            rows = db.session.query(CachedSkill).filter_by(character_id=cid).all()
            skill_ids = {r.skill_id for r in rows}
            assert 9999 not in skill_ids
            assert len(rows) == 2

    @responses.activate
    def test_skills_failure_retries(self, app, test_user):
        """Non-200 from ESI raises retry."""
        from celery.exceptions import MaxRetriesExceededError
        from src.tasks import fetch_skills_task

        cid = test_user.character_id
        _mock_skills(cid, status=500)
        _mock_skills(cid, status=500)
        _mock_skills(cid, status=500)

        with app.app_context():
            with pytest.raises((Exception, MaxRetriesExceededError)):
                fetch_skills_task(cid)

    @responses.activate
    def test_active_vs_trained_levels_stored(self, app, test_user):
        """Both active and trained skill levels are stored correctly."""
        from src.tasks import fetch_skills_task

        cid = test_user.character_id
        paused_skill = [
            {
                "skill_id": 3380,
                "trained_skill_level": 5,
                "active_skill_level": 0,
                "skillpoints_in_skill": 256000,
            }
        ]
        _mock_skills(cid, paused_skill)

        with app.app_context():
            fetch_skills_task(cid)

        with app.app_context():
            row = db.session.query(CachedSkill).filter_by(
                character_id=cid, skill_id=3380
            ).one()
            assert row.trained_skill_level == 5
            assert row.active_skill_level == 0
            assert row.skillpoints_in_skill == 256000

    @responses.activate
    def test_empty_skills_list(self, app, test_user):
        """Handles ESI returning an empty skills list gracefully."""
        from src.tasks import fetch_skills_task

        cid = test_user.character_id
        _mock_skills(cid, skills=[])

        with app.app_context():
            result = fetch_skills_task(cid)

        with app.app_context():
            rows = db.session.query(CachedSkill).filter_by(character_id=cid).all()
            assert len(rows) == 0
            assert result["skills_count"] == 0


class TestFetchBlueprintsTaskSkills:
    """Test that fetch_blueprints_task dispatches skill tasks."""

    @pytest.fixture(autouse=True)
    def _clean(self, app):
        """Remove cached skills/blueprints before each test."""
        with app.app_context():
            db.session.execute(CachedSkill.__table__.delete())
            db.session.execute(CachedBlueprint.__table__.delete())
            db.session.commit()
        yield

    @responses.activate
    def test_blueprints_dispatch_skills(self, app, test_user):
        """Blueprint task dispatches skill tasks which cache skills (eager mode)."""
        from src.tasks import fetch_blueprints_task

        cid = test_user.character_id
        _mock_blueprints(cid)
        _mock_skills(cid, SAMPLE_SKILLS)

        with app.app_context():
            result = fetch_blueprints_task(cid)

        with app.app_context():
            rows = db.session.query(CachedSkill).filter_by(character_id=cid).all()
            assert len(rows) == 2
            assert result["skills_dispatched"] == 1

    @responses.activate
    def test_skills_failure_doesnt_break_blueprints(self, app, test_user):
        """If skills ESI returns non-200, blueprints are still cached."""
        from src.tasks import fetch_blueprints_task

        cid = test_user.character_id
        bp_data = [
            {
                "item_id": 1000000001,
                "type_id": 688,
                "location_id": 60003760,
                "location_flag": "Hangar",
                "quantity": -1,
                "runs": -1,
                "material_efficiency": 10,
                "time_efficiency": 20,
            }
        ]
        _mock_blueprints(cid, bp_data)
        # Skills will fail - mock 3 times for retries
        _mock_skills(cid, status=500)
        _mock_skills(cid, status=500)
        _mock_skills(cid, status=500)
        # Mock location resolution for the blueprint's station
        responses.add(
            responses.GET,
            f"{ESI_BASE}/universe/stations/60003760/",
            json={"name": "Jita IV - Moon 4"},
            status=200,
        )

        with app.app_context():
            _ = fetch_blueprints_task(cid)

        with app.app_context():
            bps = db.session.query(CachedBlueprint).filter_by(character_id=cid).all()
            assert len(bps) == 1
            skills = db.session.query(CachedSkill).filter_by(character_id=cid).all()
            assert len(skills) == 0
