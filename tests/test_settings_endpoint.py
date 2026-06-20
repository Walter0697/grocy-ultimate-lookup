import asyncio

from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogSettings,
    CommunityCatalogSettingsUpdate,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
    LookupSettingsUpdate,
)
from app.main import (
    get_community_catalog_sources,
    get_community_catalog_settings,
    get_agent_search_availability,
    get_lookup_settings,
    put_community_catalog_sources,
    put_community_catalog_settings,
    put_lookup_settings,
    settings_page_html,
    test_community_catalog_settings as check_community_catalog_settings,
)


def run(coro):
    return asyncio.run(coro)


def test_settings_page_includes_settings_script() -> None:
    html = settings_page_html()

    assert "/static/settings.js?v=" in html
    assert "/static/settings.css?v=" in html
    assert "/static/vendor/sortable.min.js?v=" in html


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


def test_lookup_settings_endpoint_reads_and_saves_without_exposing_api_key(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    saved = run(
        put_lookup_settings(
            LookupSettingsUpdate(
                enable_open_facts=False,
                enable_upcitemdb=True,
                enable_web_search=True,
                web_search_provider="searxng",
                searxng_base_url="http://searxng:8080",
                enable_llm_fallback=True,
                llm_base_url="http://llm.test/v1",
                llm_api_key="secret-token",
                llm_model="test-model",
            )
        )
    )
    loaded = run(get_lookup_settings())

    assert saved.enable_open_facts is False
    assert saved.web_search_provider == "searxng"
    assert saved.llm_api_key_set is True
    assert loaded.llm_api_key_set is True
    assert not hasattr(loaded, "llm_api_key")


def test_agent_search_availability_reports_runtime_capability(monkeypatch, tmp_path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{}")
    monkeypatch.setattr("app.main.settings.enable_agent_search", True)
    monkeypatch.setattr("app.main.settings.agent_search_auth_path", str(auth_file))
    monkeypatch.setattr("app.main.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)

    status = run(get_agent_search_availability())

    assert status["available"] is True
    assert status["status"] == "Codex based search is available"
