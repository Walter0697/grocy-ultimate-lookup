from app.app_settings import AppSettingsStore, CommunityCatalogSettings
from app.community_catalog import RuntimeCommunityCatalogExporter
from app.models import ConfirmedProductRequest


def test_app_settings_store_returns_defaults_before_user_saves(tmp_path) -> None:
    defaults = CommunityCatalogSettings(
        enabled=False,
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
