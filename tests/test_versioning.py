from app.main import get_app_version


def test_app_version_matches_pyproject_metadata() -> None:
    assert get_app_version() == "0.0.1"
