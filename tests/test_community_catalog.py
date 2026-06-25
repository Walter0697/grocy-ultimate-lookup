import json
import textwrap
import subprocess
from base64 import b64encode
from datetime import UTC, datetime

from app.community_catalog import (
    CATALOG_MANIFEST,
    CATALOG_README,
    CATALOG_TYPE,
    CatalogValidationResult,
    CommunityCatalogExporter,
    CommunityCatalogSourceRegistry,
    RuntimeCommunityCatalogExporter,
    catalog_product_dir,
)
from app.community_catalog_queue import CommunityCatalogQueue
from app.app_settings import AppSettingsStore, CommunityCatalogSettings, CommunityCatalogSource, CommunityCatalogSourceList
from app.models import ConfirmedProductRequest


class FakeGitRunner:
    def __init__(
        self,
        *,
        fail_clone: bool = False,
        fail_fetch_missing_branch: bool = False,
        status_stdout: str = "",
    ) -> None:
        self.commands = []
        self.fail_clone = fail_clone
        self.fail_fetch_missing_branch = fail_fetch_missing_branch
        self.status_stdout = status_stdout

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if "clone" in command:
            if self.fail_clone:
                raise subprocess.CalledProcessError(
                    128,
                    command,
                    stderr="remote: Repository not found.\nfatal: Authentication failed",
                )
            destination = command[-1]
            from pathlib import Path

            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            (path / ".git").mkdir()
        if command[:2] == ["git", "fetch"] and self.fail_fetch_missing_branch:
            raise subprocess.CalledProcessError(
                128,
                command,
                stderr="fatal: couldn't find remote ref main",
            )
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout=self.status_stdout, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_catalog_product_dir_uses_two_three_digit_shards_and_full_barcode() -> None:
    assert catalog_product_dir("627985000070").as_posix() == "products/627/985/627985000070"
    assert catalog_product_dir("83400090029449960471").as_posix() == "products/834/000/83400090029449960471"
    assert catalog_product_dir("12345").as_posix() == "products/123/45/12345"


def test_exporter_writes_confirmed_product_json(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=True)

    result = exporter.export_confirmed_product(
        "627985000070",
        ConfirmedProductRequest(
            name="Manual Product",
            brand="Manual Brand",
            quantity="500 mL",
            image_url="https://example.test/product.jpg",
            notes="Typed in dashboard",
        ),
    )

    product_path = tmp_path / "products" / "627" / "985" / "627985000070" / "product.json"
    payload = json.loads(product_path.read_text())
    assert result.product_json_path == product_path
    assert payload["schema_version"] == 1
    assert payload["barcode"] == "627985000070"
    assert payload["name"] == "Manual Product"
    assert payload["brand"] == "Manual Brand"
    assert payload["quantity"] == "500 mL"
    assert payload["image_url"] == "https://example.test/product.jpg"
    assert payload["source"] == "user_confirmed"
    assert payload["confirmed_at"]


def test_exporter_copies_dashboard_uploaded_image(tmp_path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "uploaded-product.jpg").write_bytes(b"uploaded-image")
    exporter = CommunityCatalogExporter(
        path=tmp_path / "catalog",
        enabled=True,
        export_images=True,
        uploaded_images_path=uploads,
        uploaded_images_base_url="http://host.docker.internal:9290/uploaded-images",
    )

    result = exporter.export_confirmed_product(
        "627985000070",
        ConfirmedProductRequest(
            name="Manual Product",
            image_url="http://host.docker.internal:9290/uploaded-images/uploaded-product.jpg",
        ),
    )

    image_path = tmp_path / "catalog" / "products" / "627" / "985" / "627985000070" / "image.jpg"
    product_path = tmp_path / "catalog" / "products" / "627" / "985" / "627985000070" / "product.json"
    payload = json.loads(product_path.read_text())
    assert result.warnings == ()
    assert image_path.read_bytes() == b"uploaded-image"
    assert "image_url" not in payload


def test_exporter_clones_writes_commits_and_pushes_with_pat(tmp_path) -> None:
    runner = FakeGitRunner()
    checkout = tmp_path / "checkout"
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        github_pat="secret-token",
        branch="catalog",
        auto_push=True,
        author_name="GUL Bot",
        author_email="gul@example.test",
        command_runner=runner,
    )

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    commands = [call[0] for call in runner.commands]
    clone_env = runner.commands[0][1]["env"]
    assert result.exported is True
    assert commands[0] == [
        "git",
        "clone",
        "https://github.com/example/catalog.git",
        str(checkout),
    ]
    assert commands[1] == ["git", "checkout", "catalog"]
    assert clone_env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    expected_auth = b64encode(b"x-access-token:secret-token").decode()
    assert clone_env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected_auth}"
    assert "secret-token" not in clone_env["GIT_CONFIG_VALUE_0"]
    assert ["git", "add", "products/627/985/627985000070", "README.md", CATALOG_MANIFEST] in commands
    assert ["git", "commit", "-m", "Add product 627985000070"] in commands
    assert ["git", "push", "origin", "catalog"] in commands
    assert (checkout / "products" / "627" / "985" / "627985000070" / "product.json").exists()
    assert (checkout / "README.md").read_text() == CATALOG_README
    assert json.loads((checkout / CATALOG_MANIFEST).read_text())["type"] == CATALOG_TYPE


def test_exporter_checkout_failure_reports_git_stderr(tmp_path) -> None:
    runner = FakeGitRunner(fail_clone=True)
    exporter = CommunityCatalogExporter(
        path=tmp_path / "checkout",
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        github_pat="secret-token",
        auto_push=True,
        command_runner=runner,
    )

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is False
    assert result.warnings
    assert "Repository not found" in result.warnings[0]
    assert "Authentication failed" in result.warnings[0]
    assert "secret-token" not in result.warnings[0]


def test_exporter_does_not_replace_existing_catalog_readme(tmp_path) -> None:
    runner = FakeGitRunner()
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "README.md").write_text("Existing catalog readme\n")
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        branch="main",
        auto_push=True,
        command_runner=runner,
    )

    exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    commands = [call[0] for call in runner.commands]
    assert ["git", "add", "products/627/985/627985000070", CATALOG_MANIFEST] in commands
    assert not any(command == ["git", "add", "products/627/985/627985000070", "README.md"] for command in commands)
    assert (checkout / "README.md").read_text() == "Existing catalog readme\n"


def test_exporter_review_mode_syncs_and_leaves_product_uncommitted(tmp_path) -> None:
    runner = FakeGitRunner()
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        github_pat="secret-token",
        branch="main",
        auto_push=False,
        command_runner=runner,
    )

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    commands = [call[0] for call in runner.commands]
    assert result.exported is True
    assert commands[0] == ["git", "fetch", "origin", "main"]
    assert commands[1] == ["git", "reset", "--hard", "origin/main"]
    expected_auth = b64encode(b"x-access-token:secret-token").decode()
    assert runner.commands[0][1]["env"]["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected_auth}"
    assert not any("commit" in command for command in commands)
    assert not any("push" in command for command in commands)


def test_exporter_reclones_when_existing_checkout_remote_differs_from_settings(tmp_path) -> None:
    runner = FakeGitRunner()
    checkout = tmp_path / "checkout"
    git_dir = checkout / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        textwrap.dedent(
            """
            [remote "origin"]
                url = https://github.com/example/old-catalog.git
                fetch = +refs/heads/*:refs/remotes/origin/*
            [branch "main"]
                remote = origin
                merge = refs/heads/main
            """
        ).strip()
        + "\n"
    )
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        repository_url="https://github.com/example/new-catalog.git",
        branch="main",
        auto_push=False,
        command_runner=runner,
    )

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    commands = [call[0] for call in runner.commands]
    assert result.exported is True
    assert commands[0] == [
        "git",
        "clone",
        "https://github.com/example/new-catalog.git",
        str(checkout),
    ]
    assert commands[1] == ["git", "checkout", "main"]
    assert ["git", "fetch", "origin", "main"] not in commands
    assert ["git", "reset", "--hard", "origin/main"] not in commands


def test_exporter_lists_pending_products_from_git_status(tmp_path) -> None:
    runner = FakeGitRunner(
        status_stdout=(
            "?? products/627/985/627985000070/product.json\n"
            "?? products/627/985/627985000070/image.jpg\n"
            "?? README.md\n"
        )
    )
    checkout = tmp_path / "checkout"
    product_dir = checkout / "products" / "627" / "985" / "627985000070"
    (checkout / ".git").mkdir(parents=True)
    product_dir.mkdir(parents=True)
    (product_dir / "product.json").write_text(
        json.dumps({"name": "Manual Product", "brand": "Manual Brand", "quantity": "500 mL"})
    )
    (product_dir / "image.jpg").write_bytes(b"image")
    exporter = CommunityCatalogExporter(path=checkout, enabled=True, command_runner=runner)

    products = exporter.pending_products()

    assert products == [
        {
            "barcode": "627985000070",
            "path": "products/627/985/627985000070",
            "name": "Manual Product",
            "brand": "Manual Brand",
            "quantity": "500 mL",
            "has_image": True,
            "files": [
                "products/627/985/627985000070/product.json",
                "products/627/985/627985000070/image.jpg",
            ],
        }
    ]


def test_exporter_expands_directory_only_pending_product_status(tmp_path) -> None:
    runner = FakeGitRunner(status_stdout="?? products/126/\n")
    checkout = tmp_path / "checkout"
    product_dir = checkout / "products" / "126" / "146" / "12614626"
    (checkout / ".git").mkdir(parents=True)
    product_dir.mkdir(parents=True)
    (product_dir / "product.json").write_text(json.dumps({"name": "Manual Product"}))
    exporter = CommunityCatalogExporter(path=checkout, enabled=True, command_runner=runner)

    products = exporter.pending_products()

    commands = [call[0] for call in runner.commands]
    assert ["git", "status", "--porcelain", "--untracked-files=all"] in commands
    assert products[0]["barcode"] == "12614626"
    assert products[0]["path"] == "products/126/146/12614626"
    assert products[0]["name"] == "Manual Product"
    assert products[0]["files"] == ["products/126/"]


def test_exporter_pushes_selected_pending_products(tmp_path) -> None:
    runner = FakeGitRunner(
        status_stdout=(
            "?? products/627/985/627985000070/product.json\n"
            "?? products/799/253/799253441424/product.json\n"
        )
    )
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "products" / "627" / "985" / "627985000070").mkdir(parents=True)
    (checkout / "products" / "799" / "253" / "799253441424").mkdir(parents=True)
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        auto_push=False,
        command_runner=runner,
    )

    warnings = exporter.push_pending_products(["799253441424"])

    commands = [call[0] for call in runner.commands]
    assert warnings == []
    assert ["git", "add", "products/799/253/799253441424"] in commands
    assert ["git", "add", "products/627/985/627985000070"] not in commands
    assert ["git", "commit", "-m", "Add confirmed products"] in commands
    assert ["git", "push", "origin", "main"] in commands


def test_exporter_discards_selected_pending_products(tmp_path) -> None:
    runner = FakeGitRunner(
        status_stdout=(
            "?? products/627/985/627985000070/product.json\n"
            "?? products/799/253/799253441424/product.json\n"
        )
    )
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    exporter = CommunityCatalogExporter(path=checkout, enabled=True, command_runner=runner)

    warnings = exporter.discard_pending_products(["627985000070"])

    commands = [call[0] for call in runner.commands]
    assert warnings == []
    assert ["git", "restore", "--", "products/627/985/627985000070"] in commands
    assert ["git", "clean", "-fd", "--", "products/627/985/627985000070"] in commands
    assert ["git", "restore", "--", "products/799/253/799253441424"] not in commands


def test_runtime_manual_mode_queues_pending_product(tmp_path) -> None:
    from app.app_settings import CommunityCatalogSettings

    class Store:
        def get_community_catalog(self):
            return CommunityCatalogSettings(
                enabled=True,
                repository_url="https://github.com/example/catalog.git",
                github_pat=None,
                branch="main",
                workdir=str(tmp_path / "workdir"),
                path=str(tmp_path / "workdir"),
                export_images=True,
                auto_commit=False,
                auto_push=False,
                git_remote="origin",
                git_branch="main",
                author_name=None,
                author_email=None,
            )

    queue = CommunityCatalogQueue(tmp_path / "queue.sqlite3")
    runtime = RuntimeCommunityCatalogExporter(Store(), queue_store=queue)

    result = runtime.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is True
    products = runtime.pending_products()
    assert products[0]["barcode"] == "627985000070"
    assert products[0]["name"] == "Manual Product"


def test_exporter_bootstraps_existing_empty_remote_checkout(tmp_path) -> None:
    runner = FakeGitRunner(fail_fetch_missing_branch=True)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    stale_product = checkout / "products" / "111" / "222" / "111222333444" / "product.json"
    stale_product.parent.mkdir(parents=True)
    stale_product.write_text('{"name":"stale"}\n')
    exporter = CommunityCatalogExporter(
        path=checkout,
        enabled=True,
        repository_url="https://github.com/example/catalog.git",
        branch="main",
        auto_push=True,
        command_runner=runner,
    )

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    commands = [call[0] for call in runner.commands]
    assert result.exported is True
    assert result.warnings == ()
    assert commands[0] == ["git", "fetch", "origin", "main"]
    assert commands[1] == ["git", "clone", "https://github.com/example/catalog.git", str(checkout)]
    assert commands[2] == ["git", "checkout", "main"]
    assert ["git", "add", "products/627/985/627985000070", "README.md", CATALOG_MANIFEST] in commands
    assert ["git", "commit", "-m", "Add product 627985000070"] in commands
    assert ["git", "push", "origin", "main"] in commands
    assert (checkout / "README.md").read_text() == CATALOG_README
    assert json.loads((checkout / CATALOG_MANIFEST).read_text())["type"] == CATALOG_TYPE
    assert (checkout / "products" / "627" / "985" / "627985000070" / "product.json").exists()
    assert not stale_product.exists()


def test_source_registry_validates_catalog_manifest_and_counts_products(tmp_path) -> None:
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=True,
            repository_url="https://github.com/example/export.git",
            github_pat="secret-token",
            branch="main",
            workdir=str(tmp_path / "workdir" / "export"),
            path=str(tmp_path / "catalog"),
            export_images=True,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name="Walter",
            author_email="walter@example.test",
        ),
    )
    source = CommunityCatalogSource(id="source-1", repository_url="https://github.com/example/source.git")
    checkout = tmp_path / "workdir" / "community-catalog-sources" / "source-1"
    (checkout / ".git").mkdir(parents=True)
    (checkout / CATALOG_MANIFEST).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "type": CATALOG_TYPE,
                "owner": "Alice",
                "description": "Regional pantry catalog",
            }
        )
    )
    (checkout / "products" / "627" / "985" / "627985000070").mkdir(parents=True)
    (checkout / "products" / "627" / "985" / "627985000070" / "product.json").write_text(json.dumps({"name": "One"}))
    (checkout / "products" / "799" / "253" / "799253441424").mkdir(parents=True)
    (checkout / "products" / "799" / "253" / "799253441424" / "product.json").write_text(json.dumps({"name": "Two"}))

    registry = CommunityCatalogSourceRegistry(store, command_runner=FakeGitRunner())

    result = registry.validate_source(source)

    assert result.status == "valid"
    assert result.owner == "Alice"
    assert result.description == "Regional pantry catalog"
    assert result.product_count == 2


def test_source_registry_rejects_missing_catalog_manifest(tmp_path) -> None:
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=True,
            repository_url="https://github.com/example/export.git",
            github_pat="secret-token",
            branch="main",
            workdir=str(tmp_path / "workdir" / "export"),
            path=str(tmp_path / "catalog"),
            export_images=True,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name="Walter",
            author_email="walter@example.test",
        ),
    )
    source = CommunityCatalogSource(id="source-1", repository_url="https://github.com/example/source.git")
    checkout = tmp_path / "workdir" / "community-catalog-sources" / "source-1"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "products").mkdir(parents=True)

    registry = CommunityCatalogSourceRegistry(store, command_runner=FakeGitRunner())

    result = registry.validate_source(source)

    assert result.status == "invalid_manifest"
    assert result.message == "catalog.json is required"


def test_source_registry_keeps_fresh_cached_status_without_revalidation(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    source = CommunityCatalogSource(
        id="source-1",
        repository_url="https://github.com/example/source.git",
        validation_status="valid",
        validation_message="Catalog source is ready",
        last_checked=datetime.now(UTC).isoformat(),
    )
    store.set_community_catalog_sources(CommunityCatalogSourceList(sources=[source]))
    registry = CommunityCatalogSourceRegistry(store, command_runner=FakeGitRunner())

    def fail_validate(_source):
        raise AssertionError("validate_source should not run for fresh cache")

    registry.validate_source = fail_validate  # type: ignore[method-assign]

    result = registry.get_sources()

    assert result.sources[0].validation_status == "valid"


def test_source_registry_refreshes_stale_cached_status(tmp_path) -> None:
    store = AppSettingsStore(str(tmp_path / "settings.sqlite3"))
    source = CommunityCatalogSource(
        id="source-1",
        repository_url="https://github.com/example/source.git",
        validation_status="checkout_failed",
        validation_message="old failure",
        last_checked="2000-01-01T00:00:00+00:00",
    )
    store.set_community_catalog_sources(CommunityCatalogSourceList(sources=[source]))
    registry = CommunityCatalogSourceRegistry(store, command_runner=FakeGitRunner())

    registry.validate_source = lambda _source: CatalogValidationResult(  # type: ignore[method-assign]
        status="valid",
        message="Catalog source is ready",
        owner="Walter",
        product_count=2,
        last_checked=datetime.now(UTC).isoformat(),
        last_successful_check=datetime.now(UTC).isoformat(),
    )

    result = registry.get_sources()

    assert result.sources[0].validation_status == "valid"
    assert result.sources[0].owner == "Walter"
    assert result.sources[0].product_count == 2


def test_disabled_exporter_does_not_write_files(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=False)

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is False
    assert not (tmp_path / "products").exists()
