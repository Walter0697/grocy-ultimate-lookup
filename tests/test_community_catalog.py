import json
import subprocess
from base64 import b64encode

from app.community_catalog import CATALOG_README, CommunityCatalogExporter, catalog_product_dir
from app.models import ConfirmedProductRequest


class FakeGitRunner:
    def __init__(self, *, fail_clone: bool = False, fail_fetch_missing_branch: bool = False) -> None:
        self.commands = []
        self.fail_clone = fail_clone
        self.fail_fetch_missing_branch = fail_fetch_missing_branch

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
    assert ["git", "add", "products/627/985/627985000070", "README.md"] in commands
    assert ["git", "commit", "-m", "Add product 627985000070"] in commands
    assert ["git", "push", "origin", "catalog"] in commands
    assert (checkout / "products" / "627" / "985" / "627985000070" / "product.json").exists()
    assert (checkout / "README.md").read_text() == CATALOG_README


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
    assert ["git", "add", "products/627/985/627985000070"] in commands
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
    assert ["git", "add", "products/627/985/627985000070", "README.md"] in commands
    assert ["git", "commit", "-m", "Add product 627985000070"] in commands
    assert ["git", "push", "origin", "main"] in commands
    assert (checkout / "README.md").read_text() == CATALOG_README
    assert (checkout / "products" / "627" / "985" / "627985000070" / "product.json").exists()
    assert not stale_product.exists()


def test_disabled_exporter_does_not_write_files(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=False)

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is False
    assert not (tmp_path / "products").exists()
