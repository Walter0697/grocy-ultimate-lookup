import asyncio

from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogMetadata,
    CommunityCatalogSettings,
    CommunityCatalogSettingsUpdate,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
    LookupSettingsUpdate,
)
from fastapi import HTTPException
from app.main import (
    get_community_catalog_metadata,
    get_community_catalog_sources,
    get_community_catalog_settings,
    get_agent_search_availability,
    get_lookup_settings,
    put_community_catalog_metadata,
    put_community_catalog_sources,
    put_community_catalog_settings,
    put_lookup_settings,
    refresh_community_catalog_source,
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


def test_settings_page_renders_subtle_app_version_badge() -> None:
    html = settings_page_html()

    assert 'class="app-version-badge"' in html
    assert ">v0.0.1<" in html


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
                auto_push_ai_results=False,
                author_name="Walter",
                author_email="walter@example.test",
            )
        )
    )
    loaded = run(get_community_catalog_settings())

    assert saved.enabled is True
    assert saved.github_pat_set is True
    assert saved.auto_push_ai_results is False
    assert loaded.github_pat_set is True
    assert loaded.repository_url == "https://github.com/example/catalog.git"
    assert loaded.auto_push_ai_results is False
    assert not hasattr(loaded, "github_pat")


def test_community_catalog_metadata_endpoint_reads_empty_when_manifest_missing(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    class Exporter:
        def read_catalog_metadata(self):
            return CommunityCatalogMetadata()

    monkeypatch.setattr("app.main.exporter_from_settings", lambda current: Exporter())

    loaded = run(get_community_catalog_metadata())

    assert loaded == CommunityCatalogMetadata()


def test_community_catalog_metadata_endpoint_saves_and_pushes(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    store.update_community_catalog(
        CommunityCatalogSettingsUpdate(
            enabled=True,
            repository_url="https://github.com/example/catalog.git",
            github_pat="secret-token",
            branch="main",
            export_images=True,
            auto_push=True,
        )
    )
    monkeypatch.setattr("app.main.app_settings_store", store)
    calls: list[str] = []

    class Exporter:
        last_metadata = CommunityCatalogMetadata()

        def sync_checkout(self):
            calls.append("sync_checkout")
            return []

        def write_catalog_metadata(self, metadata):
            self.last_metadata = metadata
            calls.append(f"write:{metadata.model_dump()}")
            return True

        def read_catalog_metadata(self):
            return self.last_metadata

        def commit_and_push_paths(self, paths, message):
            calls.append(f"commit_and_push:{paths}:{message}")
            return []

    monkeypatch.setattr("app.main.exporter_from_settings", lambda current: Exporter())

    saved = run(
        put_community_catalog_metadata(
            CommunityCatalogMetadata(
                owner="Walter Cheng",
                description="Regional household products",
                region="Hong Kong",
                stores=["Wellcome", "ParknShop"],
                languages=["en", "zh-Hant"],
                categories=["groceries", "household"],
            )
        )
    )

    assert saved.owner == "Walter Cheng"
    assert calls == [
        "sync_checkout",
        "write:{'owner': 'Walter Cheng', 'description': 'Regional household products', 'region': 'Hong Kong', 'stores': ['Wellcome', 'ParknShop'], 'languages': ['en', 'zh-Hant'], 'categories': ['groceries', 'household']}",
        "commit_and_push:['catalog.json']:Update catalog metadata",
    ]


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

    class Registry:
        def get_sources(self):
            return store.get_community_catalog_sources()

        def validate_and_store_sources(self, sources):
            enriched = CommunityCatalogSourceList(
                sources=[
                    source.model_copy(
                        update={
                            "owner": "Walter",
                            "description": "Test catalog",
                            "product_count": 3,
                            "validation_status": "valid",
                            "validation_message": "Catalog source is ready",
                            "warnings": [],
                            "last_checked": "2026-06-25T05:00:00+00:00",
                        }
                    )
                    for source in sources.sources
                ]
            )
            return store.set_community_catalog_sources(enriched)

    monkeypatch.setattr("app.main.catalog_source_registry", Registry())

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
    assert loaded.sources[0].owner == "Walter"
    assert loaded.sources[0].product_count == 3
    assert loaded.sources[0].validation_status == "valid"


def test_community_catalog_sources_endpoint_rejects_invalid_source(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    class Registry:
        def get_sources(self):
            return store.get_community_catalog_sources()

        def validate_and_store_sources(self, sources):
            raise ValueError("catalog.json is required")

    monkeypatch.setattr("app.main.catalog_source_registry", Registry())

    try:
        run(
            put_community_catalog_sources(
                CommunityCatalogSourceList(
                    sources=[CommunityCatalogSource(repository_url="https://github.com/example/catalog.git")]
                )
            )
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "catalog.json is required"


def test_community_catalog_source_refresh_endpoint(monkeypatch, tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    monkeypatch.setattr("app.main.app_settings_store", store)

    class Registry:
        def get_sources(self):
            return store.get_community_catalog_sources()

        def validate_and_store_sources(self, sources):
            return store.set_community_catalog_sources(sources)

        def refresh_source(self, source_id):
            return CommunityCatalogSource(
                id=source_id,
                repository_url="https://github.com/example/catalog.git",
                validation_status="valid_with_warnings",
                validation_message="Catalog source is empty",
                product_count=0,
                warnings=["No product.json files found under products/"],
                last_checked="2026-06-25T05:10:00+00:00",
                last_successful_check="2026-06-25T05:10:00+00:00",
            )

    monkeypatch.setattr("app.main.catalog_source_registry", Registry())

    refreshed = run(refresh_community_catalog_source("source-1"))

    assert refreshed.id == "source-1"
    assert refreshed.validation_status == "valid_with_warnings"
    assert refreshed.product_count == 0


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
