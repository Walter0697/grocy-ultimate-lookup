import asyncio

from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogSettings,
    CommunityCatalogSettingsUpdate,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
)
from app.main import (
    get_community_catalog_sources,
    get_community_catalog_settings,
    put_community_catalog_sources,
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
            CommunityCatalogSettingsUpdate(
                enabled=True,
                repository_url="https://github.com/example/catalog.git",
                github_pat="secret-token",
                branch="main",
                export_images=True,
                auto_push=False,
                author_name="Walter",
                author_email="walter@example.test",
            )
        )
    )
    loaded = run(get_community_catalog_settings())

    assert saved.enabled is True
    assert saved.github_pat_set is True
    assert loaded.github_pat_set is True
    assert loaded.repository_url == "https://github.com/example/catalog.git"
    assert not hasattr(loaded, "github_pat")


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


def test_community_catalog_sources_endpoint_reads_and_saves(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    saved = run(
        put_community_catalog_sources(
            CommunityCatalogSourceList(
                sources=[
                    CommunityCatalogSource(
                        repository_url="https://github.com/example/catalog.git",
                        name="Example",
                    )
                ]
            )
        )
    )
    loaded = run(get_community_catalog_sources())

    assert len(saved.sources) == 1
    assert saved.sources[0].id
    assert loaded.sources[0].repository_url == "https://github.com/example/catalog.git"
