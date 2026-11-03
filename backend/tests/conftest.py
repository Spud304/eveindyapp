from pathlib import Path

import pytest


@pytest.fixture
def sde_dir(settings, tmp_path) -> Path:
    """Point the SDE instance folders at a temporary directory."""
    settings.INSTANCE_DIR = tmp_path / "instance"
    settings.SDE_DIR = settings.INSTANCE_DIR / "sde"
    return settings.SDE_DIR
