from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogSettings,
    CommunityCatalogSettingsUpdate,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
    LookupSettings,
    LookupSettingsUpdate,
    SearchProviderSetting,
)
from app.community_catalog import RuntimeCommunityCatalogExporter
from app.models import ConfirmedProductRequest


def test_app_settings_store_returns_defaults_before_user_saves(tmp_path) -> None:
    defaults = CommunityCatalogSettings(
        enabled=False,
        repository_url=None,
        github_pat=None,
        branch="main",
        workdir=str(tmp_path / "workdir"),
        path=str(tmp_path / "default-catalog"),
        export_images=False,
        auto_commit=False,
        auto_push=False,
        git_remote="origin",
        git_branch="main",
        author_name=None,
        author_email=None,
    )
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"), community_catalog_defaults=defaults)

    current = store.get_community_catalog()

    assert current == defaults


def test_app_settings_store_persists_community_catalog_settings(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    saved = CommunityCatalogSettings(
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        github_pat="secret-token",
        branch="catalog",
        workdir=str(tmp_path / "workdir"),
        path=str(tmp_path / "catalog"),
        export_images=True,
        auto_commit=True,
        auto_push=False,
        git_remote="upstream",
        git_branch="catalog",
        author_name="Walter",
        author_email="walter@example.test",
    )

    store.set_community_catalog(saved)

    reopened = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    assert reopened.get_community_catalog() == saved


def test_runtime_catalog_exporter_reads_latest_saved_settings(tmp_path) -> None:
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=False,
            repository_url=None,
            github_pat=None,
            branch="main",
            workdir=str(tmp_path / "workdir"),
            path=str(tmp_path / "disabled-catalog"),
            export_images=False,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name=None,
            author_email=None,
        ),
    )
    exporter = RuntimeCommunityCatalogExporter(store)

    disabled = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))
    store.set_community_catalog(
        CommunityCatalogSettings(
            enabled=True,
            repository_url=None,
            github_pat=None,
            branch="main",
            workdir=str(tmp_path / "workdir"),
            path=str(tmp_path / "enabled-catalog"),
            export_images=False,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name=None,
            author_email=None,
        )
    )
    enabled = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert disabled.exported is False
    assert enabled.exported is True
    assert (tmp_path / "enabled-catalog" / "products" / "627" / "985" / "627985000070" / "product.json").exists()


def test_app_settings_store_reports_catalog_path_status(tmp_path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / ".git").mkdir()
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=True,
            repository_url=None,
            github_pat=None,
            branch="main",
            workdir=str(tmp_path / "workdir"),
            path=str(catalog),
            export_images=False,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name=None,
            author_email=None,
        ),
    )

    status = store.community_catalog_status()

    assert status.path == str(catalog)
    assert status.path_exists is True
    assert status.is_git_repo is True


def test_app_settings_update_preserves_saved_pat_when_blank(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))

    first = store.update_community_catalog(
        CommunityCatalogSettingsUpdate(
            enabled=True,
            repository_url="https://github.com/example/catalog.git",
            github_pat="secret-token",
            branch="main",
            auto_push=True,
        )
    )
    second = store.update_community_catalog(
        CommunityCatalogSettingsUpdate(
            enabled=True,
            repository_url="https://github.com/example/catalog.git",
            github_pat=None,
            branch="catalog",
            auto_push=False,
        )
    )

    assert first.github_pat == "secret-token"
    assert second.github_pat == "secret-token"
    assert second.branch == "catalog"
    assert second.auto_push is False


def test_app_settings_store_persists_auto_push_ai_results(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))

    saved = store.update_community_catalog(
        CommunityCatalogSettingsUpdate(
            enabled=True,
            repository_url="https://github.com/example/catalog.git",
            github_pat="secret-token",
            branch="main",
            auto_push=True,
            auto_push_ai_results=False,
        )
    )
    reopened = AppSettingsStore(str(tmp_path / "settings.sqlite3")).get_community_catalog()

    assert saved.auto_push is True
    assert saved.auto_push_ai_results is False
    assert reopened.auto_push_ai_results is False


def test_app_settings_store_persists_ordered_community_catalog_sources(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))

    saved = store.set_community_catalog_sources(
        CommunityCatalogSourceList(
            sources=[
                CommunityCatalogSource(
                    name="Second",
                    repository_url="https://github.com/example/second.git",
                    enabled=False,
                ),
                CommunityCatalogSource(
                    name="First",
                    repository_url="https://github.com/example/first.git",
                    enabled=True,
                ),
            ]
        )
    )

    reopened = AppSettingsStore(str(tmp_path / "settings.sqlite3")).get_community_catalog_sources()
    assert [source.repository_url for source in saved.sources] == [
        "https://github.com/example/second.git",
        "https://github.com/example/first.git",
    ]
    assert [source.priority for source in reopened.sources] == [0, 1]
    assert all(source.id for source in reopened.sources)
    assert reopened.sources[0].enabled is False


def test_app_settings_store_persists_lookup_settings_and_preserves_llm_key(tmp_path) -> None:
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        lookup_defaults=LookupSettings(enable_open_facts=True, enable_upcitemdb=True, enable_web_search=True),
    )

    first = store.update_lookup(
        LookupSettingsUpdate(
            enable_open_facts=False,
            enable_upcitemdb=True,
            enable_web_search=True,
            web_search_provider="searxng",
            searxng_base_url="http://searxng:8080",
            enable_llm_fallback=True,
            llm_base_url="http://ollama:11434/v1",
            llm_api_key="secret-key",
            llm_model="local-model",
        )
    )
    second = store.update_lookup(
        LookupSettingsUpdate(
            enable_open_facts=True,
            enable_upcitemdb=False,
            enable_web_search=False,
            web_search_provider="duckduckgo",
            enable_llm_fallback=False,
            llm_api_key=None,
            llm_model=None,
        )
    )

    assert first.llm_api_key == "secret-key"
    assert second.llm_api_key == "secret-key"
    assert second.enable_open_facts is True
    assert second.enable_upcitemdb is False
    assert second.enable_web_search is False


def test_lookup_settings_persist_search_provider_order(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))

    saved = store.update_lookup(
        LookupSettingsUpdate(
            search_providers=[
                SearchProviderSetting(id="web_search", enabled=True, priority=0),
                SearchProviderSetting(id="upcitemdb", enabled=False, priority=1),
                SearchProviderSetting(id="open_food_facts", enabled=True, priority=2),
            ]
        )
    )
    reopened = AppSettingsStore(str(tmp_path / "settings.sqlite3")).get_lookup()

    assert [provider.id for provider in saved.search_providers[:3]] == [
        "web_search",
        "upcitemdb",
        "open_food_facts",
    ]
    assert reopened.search_providers[1].enabled is False
    assert any(provider.id == "grocy_current" for provider in reopened.search_providers)
    assert any(provider.id == "community_catalog" for provider in reopened.search_providers)
    assert any(provider.id == "codex_agent" for provider in reopened.search_providers)
