import tomllib
from pathlib import Path

from app.main import get_app_version


def test_app_version_matches_pyproject_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert get_app_version() == pyproject["project"]["version"]
