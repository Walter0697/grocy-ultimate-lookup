import asyncio

from app.app_settings import AppSettingsStore, CommunityCatalogSettings
from app.main import (
    get_community_catalog_settings,
    put_community_catalog_settings,
    settings_page_html,
    test_community_catalog_settings as check_community_catalog_settings,
)


def run(coro):
    return asyncio.run(coro)


def test_settings_page_includes_settings_script() -> None:
    html = settings_page_html()

    assert "/static/settings.js?v=" in html
    assert "/static/settings.css?v=" in html


def test_community_catalog_settings_endpoint_reads_and_saves(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    saved = run(
        put_community_catalog_settings(
            CommunityCatalogSettings(
                enabled=True,
                path=str(tmp_path / "catalog"),
                export_images=True,
                auto_commit=True,
                auto_push=False,
                git_remote="origin",
                git_branch="main",
                author_name="Walter",
                author_email="walter@example.test",
            )
        )
    )
    loaded = run(get_community_catalog_settings())

    assert saved.enabled is True
    assert loaded == saved


def test_community_catalog_settings_test_reports_path_status(monkeypatch, tmp_path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(path=str(catalog)),
    )
    monkeypatch.setattr("app.main.app_settings_store", store)

    status = run(check_community_catalog_settings())

    assert status.path == str(catalog)
    assert status.path_exists is True
    assert status.is_git_repo is False
