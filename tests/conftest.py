import os
import tempfile

# Set env vars BEFORE any src imports
os.environ.setdefault("CLIENT_ID", "test-client-id")
os.environ.setdefault("CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("CALLBACK_URL", "http://localhost:5050/callback")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("STATIC_DB", "test_static")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("SCOPES", '["publicData"]')

import pytest
from datetime import datetime, timezone, timedelta
from flask_login import LoginManager
from sqlalchemy import text

from src.application import Application
from src.celery_app import celery_init_app
from src.models.models import (
    db,
    User,
    InvTypes,
    InvGroups,
    IndustryActivityMaterials,
    IndustryActivityProducts,
    IndustryBlueprints,
    MapSolarSystems,
)
from src.auth import AuthBlueprint
from src.user import UserBlueprint
from src.industry import IndustryBlueprint
from src.config import ConfigBlueprint


def _seed_static_data():
    """Insert minimal SDE fixture data into the in-memory static DB."""
    # Create dgmTypeAttributes table (no ORM model)
    engine = db.engines["static"]
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS dgmTypeAttributes (
                typeID INTEGER,
                attributeID INTEGER,
                valueInt INTEGER,
                valueFloat REAL,
                PRIMARY KEY (typeID, attributeID)
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS industryActivity (
                typeID INTEGER,
                activityID INTEGER,
                time INTEGER,
                PRIMARY KEY (typeID, activityID)
            )
        """)
        )
        conn.commit()

    # Groups
    groups = [
        InvGroups(groupID=25, categoryID=6, groupName="Frigate"),
        InvGroups(groupID=26, categoryID=6, groupName="Cruiser"),
        InvGroups(groupID=18, categoryID=7, groupName="Armor Module"),
        InvGroups(groupID=85, categoryID=8, groupName="Projectile Ammo"),
        InvGroups(groupID=100, categoryID=18, groupName="Combat Drone"),
        InvGroups(groupID=334, categoryID=17, groupName="Construction Components"),
        InvGroups(
            groupID=873, categoryID=17, groupName="Capital Construction Components"
        ),
        InvGroups(groupID=536, categoryID=17, groupName="Structure Components"),
        InvGroups(groupID=1816, categoryID=66, groupName="Rig Equipment M-Set"),
    ]
    for g in groups:
        db.session.merge(g)

    # Types - raw materials
    raw_types = [
        InvTypes(typeID=34, groupID=18, typeName="Tritanium", published=True),
        InvTypes(typeID=35, groupID=18, typeName="Pyerite", published=True),
        InvTypes(typeID=36, groupID=18, typeName="Mexallon", published=True),
    ]
    for t in raw_types:
        db.session.merge(t)

    # Types - products and blueprints
    product_types = [
        InvTypes(typeID=587, groupID=25, typeName="Rifter", published=True),
        InvTypes(typeID=688, groupID=105, typeName="Rifter Blueprint", published=True),
        # A sub-component that has its own blueprint
        InvTypes(typeID=9001, groupID=334, typeName="Test Component", published=True),
        InvTypes(
            typeID=9002,
            groupID=105,
            typeName="Test Component Blueprint",
            published=True,
        ),
        # A rig type for ME tests
        InvTypes(
            typeID=37178,
            groupID=1816,
            typeName="Standup M-Set Equipment Manufacturing Material Efficiency II",
            published=True,
        ),
    ]
    for t in product_types:
        db.session.merge(t)

    # Manufacturing activities: Rifter Blueprint produces Rifter
    activities_products = [
        IndustryActivityProducts(
            typeID=688, activityID=1, productTypeID=587, quantity=1
        ),
        IndustryActivityProducts(
            typeID=9002, activityID=1, productTypeID=9001, quantity=1
        ),
    ]
    for a in activities_products:
        db.session.merge(a)

    # Manufacturing materials: Rifter needs Tritanium, Pyerite, and Test Component
    activities_materials = [
        IndustryActivityMaterials(
            typeID=688, activityID=1, materialTypeID=34, quantity=2000
        ),
        IndustryActivityMaterials(
            typeID=688, activityID=1, materialTypeID=35, quantity=1000
        ),
        IndustryActivityMaterials(
            typeID=688, activityID=1, materialTypeID=9001, quantity=5
        ),
        # Test Component needs raw mats only
        IndustryActivityMaterials(
            typeID=9002, activityID=1, materialTypeID=34, quantity=100
        ),
        IndustryActivityMaterials(
            typeID=9002, activityID=1, materialTypeID=36, quantity=50
        ),
    ]
    for m in activities_materials:
        db.session.merge(m)

    # Blueprint info
    bp_info = [
        IndustryBlueprints(typeID=688, maxProductionLimit=300),
        IndustryBlueprints(typeID=9002, maxProductionLimit=600),
    ]
    for b in bp_info:
        db.session.merge(b)

    # Solar systems
    systems = [
        MapSolarSystems(solarSystemID=30000142, solarSystemName="Jita", security=0.9),
        MapSolarSystems(solarSystemID=30002187, solarSystemName="Amarr", security=1.0),
        MapSolarSystems(solarSystemID=30002053, solarSystemName="Hek", security=0.5),
    ]
    for s in systems:
        db.session.merge(s)

    # Rig dogma attributes (for ME rig testing)
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT OR REPLACE INTO dgmTypeAttributes (typeID, attributeID, valueInt, valueFloat)
            VALUES
                (37178, 2594, NULL, -2.0),
                (37178, 2355, NULL, 1.0),
                (37178, 2356, NULL, 1.9),
                (37178, 2357, NULL, 2.1)
        """)
        )
        # Activity times: mfg (activityID=1) and copy (activityID=5) for blueprints
        conn.execute(
            text("""
            INSERT OR REPLACE INTO industryActivity (typeID, activityID, time)
            VALUES
                (688, 1, 3600),
                (688, 5, 1800),
                (9002, 1, 7200),
                (9002, 5, 3600)
        """)
        )
        conn.commit()

    db.session.commit()


def create_test_app():
    """Build a Flask app configured for testing with in-memory SQLite."""
    tmp = tempfile.mkdtemp()
    src_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
    )
    app = Application("src.main", instance_path=tmp, root_path=src_dir)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"

    # Use in-memory SQLite with shared cache so default + "base" share one DB
    # (User model has no bind_key, CachedBlueprint/UserConfig use "base")
    shared_uri = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"
    app.config["SQLALCHEMY_DATABASE_URI"] = shared_uri
    app.config["SQLALCHEMY_BINDS"] = {
        "static": "sqlite://",
        "base": shared_uri,
    }

    app.config["CELERY"] = {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True,
        "task_eager_propagates": True,
    }

    db.init_app(app)
    celery_init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    auth_bp = AuthBlueprint(
        "auth", "src", "test-client-id", "test-client-secret", scopes="publicData"
    )
    app.register_blueprint(auth_bp)
    app.register_blueprint(UserBlueprint("user", "src"))
    app.register_blueprint(IndustryBlueprint("industry", "src"))
    app.register_blueprint(ConfigBlueprint("config", "src"))

    with app.app_context():
        db.create_all()
        _seed_static_data()

    return app


@pytest.fixture(scope="session")
def app():
    """Session-scoped test app."""
    return create_test_app()


@pytest.fixture(autouse=True)
def _cleanup(app):
    """Reset DB session after each test."""
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture()
def client(app):
    """Per-test Flask test client."""
    return app.test_client()


@pytest.fixture()
def test_user(app):
    """Create and return a test User (cleaned up after test via rollback)."""
    with app.app_context():
        user = User(
            character_id=12345678,
            character_name="TestPilot",
            character_owner_hash="testhash",
            main_character_id=12345678,
            access_token="test-access-token",
            access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token="test-refresh-token",
        )
        db.session.merge(user)
        db.session.commit()
        return user


@pytest.fixture()
def auth_client(app, client, test_user):
    """Test client with an authenticated session."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(test_user.character_id)
    return client
