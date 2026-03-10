"""Tests for config logic in src/config.py."""

import json
from datetime import datetime, timezone

from src.config import load_user_config
from src.models.models import db, UserConfig


class TestLoadUserConfig:
    def test_no_row_returns_defaults(self, app):
        with app.app_context():
            config = load_user_config(99999)
            assert config == {
                "stations": [],
                "blacklist": [],
                "build_slots": 10,
                "copy_slots": 10,
                "default_timeframe_hours": None,
            }

    def test_valid_json(self, app, test_user):
        with app.app_context():
            db.session.merge(
                UserConfig(
                    character_id=test_user.character_id,
                    config_json=json.dumps(
                        {
                            "stations": [{"id": 1, "name": "Test"}],
                            "blacklist": [34],
                        }
                    ),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

            config = load_user_config(test_user.character_id)
            assert len(config["stations"]) == 1
            assert config["stations"][0]["name"] == "Test"
            assert 34 in config["blacklist"]

    def test_invalid_json_returns_defaults(self, app, test_user):
        with app.app_context():
            db.session.merge(
                UserConfig(
                    character_id=test_user.character_id,
                    config_json="not valid json {{{",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

            config = load_user_config(test_user.character_id)
            assert config == {
                "stations": [],
                "blacklist": [],
                "build_slots": 10,
                "copy_slots": 10,
                "default_timeframe_hours": None,
            }

    def test_partial_config_gets_defaults(self, app, test_user):
        with app.app_context():
            db.session.merge(
                UserConfig(
                    character_id=test_user.character_id,
                    config_json=json.dumps({"stations": [{"id": 1, "name": "S"}]}),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

            config = load_user_config(test_user.character_id)
            assert len(config["stations"]) == 1
            assert config["blacklist"] == []
