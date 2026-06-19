import json
import subprocess

from app.community_catalog import CommunityCatalogExporter, catalog_product_dir
from app.models import ConfirmedProductRequest


class FakeGitRunner:
    def __init__(self) -> None:
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if "clone" in command:
            destination = command[-1]
            from pathlib import Path

            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            (path / ".git").mkdir()
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
    assert clone_env["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer secret-token"
    assert ["git", "add", "products/627/985/627985000070"] in commands
    assert ["git", "commit", "-m", "Add product 627985000070"] in commands
    assert ["git", "push", "origin", "catalog"] in commands
    assert (checkout / "products" / "627" / "985" / "627985000070" / "product.json").exists()


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
    assert runner.commands[0][1]["env"]["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer secret-token"
    assert not any("commit" in command for command in commands)
    assert not any("push" in command for command in commands)


def test_disabled_exporter_does_not_write_files(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=False)

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is False
    assert not (tmp_path / "products").exists()
