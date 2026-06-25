from __future__ import annotations

import configparser
import json
import logging
import os
import shutil
import subprocess
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from app.app_settings import CommunityCatalogSource, CommunityCatalogSourceList
from app.config import settings
from app.models import ConfirmedProductRequest

logger = logging.getLogger(__name__)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
CATALOG_SCHEMA_VERSION = 1
CATALOG_TYPE = "grocy-community-catalog"
CATALOG_MANIFEST = "catalog.json"
SOURCE_STATUS_TTL = timedelta(minutes=10)

CATALOG_README = """# Grocy Community Catalog

Welcome. This repository is a product catalog created by Grocy Ultimate Lookup.

Products are stored by barcode under the `products/` directory. Each product folder can contain a `product.json` file and, when image export is enabled, an `image.jpg` file.

This catalog can be produced by connecting your own product scanning workflow to Grocy Ultimate Lookup and confirming products as you scan them.

This catalog is not meant to compete with Open Food Facts, Open Products Facts, Open Beauty Facts, or other open product databases. It is a Grocy-ready bridge for products that are missing, ambiguous, regional, or better represented by a community-specific catalog. Future Grocy Ultimate Lookup versions may help review catalog records for contribution back to open databases without blindly polluting public data.

See [Grocy Ultimate Lookup](https://github.com/Walter0697/grocy-ultimate-lookup) for how the catalog format works and how to run the lookup service.
"""


@dataclass(frozen=True)
class CommunityCatalogExportResult:
    exported: bool
    product_json_path: Path | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogValidationResult:
    status: str
    message: str
    owner: str | None = None
    description: str | None = None
    product_count: int | None = None
    warnings: tuple[str, ...] = ()
    last_checked: str | None = None
    last_successful_check: str | None = None
    last_failed_check: str | None = None
    last_error: str | None = None


def catalog_product_dir(barcode: str) -> Path:
    safe_barcode = sanitize_barcode(barcode)
    return Path("products") / safe_barcode[:3] / safe_barcode[3:6] / safe_barcode


def sanitize_barcode(barcode: str) -> str:
    safe = "".join(char for char in barcode.strip() if char.isalnum() or char in {"-", "_"})
    if not safe:
        raise ValueError("barcode must contain at least one path-safe character")
    return safe


class CommunityCatalogExporter:
    def __init__(
        self,
        path: str | Path,
        *,
        enabled: bool = False,
        export_images: bool = False,
        auto_commit: bool = False,
        auto_push: bool = False,
        git_remote: str = "origin",
        git_branch: str = "main",
        repository_url: str | None = None,
        github_pat: str | None = None,
        branch: str | None = None,
        author_name: str | None = None,
        author_email: str | None = None,
        uploaded_images_path: str | Path | None = None,
        uploaded_images_base_url: str | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.export_images = export_images
        self.auto_commit = auto_commit
        self.auto_push = auto_push
        self.git_remote = git_remote
        self.git_branch = branch or git_branch
        self.repository_url = repository_url
        self.github_pat = github_pat
        self.author_name = author_name
        self.author_email = author_email
        self.uploaded_images_path = Path(uploaded_images_path) if uploaded_images_path else None
        self.uploaded_images_base_url = uploaded_images_base_url
        self.command_runner = command_runner or subprocess.run

    def export_confirmed_product(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
        *,
        local_image_path: str | Path | None = None,
        sync_checkout: bool = True,
    ) -> CommunityCatalogExportResult:
        if not self.enabled:
            return CommunityCatalogExportResult(exported=False)

        warnings: list[str] = []
        if self.repository_url and sync_checkout:
            warnings.extend(self._sync_checkout())
            if warnings:
                return CommunityCatalogExportResult(exported=False, warnings=tuple(warnings))

        product_dir = self.path / catalog_product_dir(barcode)
        product_dir.mkdir(parents=True, exist_ok=True)
        product_json_path = product_dir / "product.json"
        payload = self._product_payload(barcode, product, local_image_path=local_image_path)
        product_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

        if self.export_images and (product.image_url is not None or local_image_path is not None):
            try:
                self._write_product_image(
                    str(product.image_url) if product.image_url is not None else None,
                    product_dir / "image.jpg",
                    local_image_path=local_image_path,
                )
            except Exception as exc:
                warnings.append(f"image export failed: {exc}")
                logger.warning("Community catalog image export failed for %s: %s", barcode, exc)

        if self.auto_commit or (self.repository_url and self.auto_push):
            warnings.extend(self._commit_and_maybe_push(product_json_path, barcode))

        return CommunityCatalogExportResult(
            exported=True,
            product_json_path=product_json_path,
            warnings=tuple(warnings),
        )

    def _ensure_readme(self) -> bool:
        readme_path = self.path / "README.md"
        if readme_path.exists():
            return False
        readme_path.write_text(CATALOG_README)
        return True

    def _ensure_catalog_manifest(self) -> bool:
        manifest_path = self.path / CATALOG_MANIFEST
        if manifest_path.exists():
            return False
        payload = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "type": CATALOG_TYPE,
        }
        if self.author_name:
            payload["owner"] = self.author_name
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return True

    def _product_payload(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
        *,
        local_image_path: str | Path | None = None,
    ) -> dict:
        payload = {
            "schema_version": 1,
            "barcode": barcode,
            "name": product.name.strip(),
            "brand": product.brand,
            "quantity": product.quantity,
            "size": product.size,
            "count": product.count,
            "variant": product.variant,
            "notes": product.notes,
            "source": "user_confirmed",
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        if local_image_path is None and product.image_url is not None and not self._is_uploaded_image_url(str(product.image_url)):
            payload["image_url"] = str(product.image_url)
        return payload

    def _write_product_image(
        self,
        image_url: str | None,
        image_path: Path,
        *,
        local_image_path: str | Path | None = None,
    ) -> None:
        if local_image_path is not None:
            shutil.copyfile(Path(local_image_path), image_path)
            return
        if image_url is not None and self._copy_uploaded_image(image_url, image_path):
            return
        if image_url is None:
            raise ValueError("image URL is required when no local image path is provided")
        self._download_image(image_url, image_path)

    def _copy_uploaded_image(self, image_url: str, image_path: Path) -> bool:
        if not self._is_uploaded_image_url(image_url):
            return False
        relative_name = self._uploaded_image_name(image_url)
        if not self.uploaded_images_path:
            return False
        source_path = self.uploaded_images_path / relative_name
        if not source_path.is_file():
            raise FileNotFoundError(f"uploaded image file not found: {relative_name}")
        shutil.copyfile(source_path, image_path)
        return True

    def _is_uploaded_image_url(self, image_url: str) -> bool:
        if not (self.uploaded_images_path and self.uploaded_images_base_url):
            return False
        base = urlparse(self.uploaded_images_base_url.rstrip("/") + "/")
        source = urlparse(image_url)
        if (source.scheme, source.netloc) != (base.scheme, base.netloc):
            return False
        if not source.path.startswith(base.path):
            return False
        relative_name = unquote(source.path[len(base.path) :])
        if "/" in relative_name or "\\" in relative_name or not relative_name:
            raise ValueError("uploaded image URL must reference a single uploaded file")
        return True

    def _uploaded_image_name(self, image_url: str) -> str:
        base = urlparse(self.uploaded_images_base_url.rstrip("/") + "/") if self.uploaded_images_base_url else None
        if base is None:
            raise ValueError("uploaded image base URL is not configured")
        return unquote(urlparse(image_url).path[len(base.path) :])

    @staticmethod
    def _download_image(image_url: str, image_path: Path) -> None:
        request = urllib.request.Request(image_url, headers={"User-Agent": "GrocyUltimateLookup/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            image_path.write_bytes(response.read())

    def _commit_and_maybe_push(self, product_json_path: Path, barcode: str) -> list[str]:
        warnings: list[str] = []
        relative_product_dir = product_json_path.parent.relative_to(self.path)
        commit_paths: list[Path | str] = [relative_product_dir]
        if self.repository_url and self._ensure_readme():
            commit_paths.append("README.md")
        if self.repository_url and self._ensure_catalog_manifest():
            commit_paths.append(CATALOG_MANIFEST)
        commit_message = f"Add product {barcode}"
        env = self._git_env(self._git_author_env())
        warnings.extend(self._commit_paths(commit_paths, commit_message, env=env))
        if warnings:
            return warnings
        if self.auto_push:
            warnings.extend(self._run_git_sequence([self._git_command(["push", self.git_remote, self.git_branch])], env=env))
        return warnings

    def _commit_path(self, relative_path: Path | str, message: str, *, env: dict[str, str] | None) -> list[str]:
        return self._commit_paths([relative_path], message, env=env)

    def _commit_paths(self, relative_paths: list[Path | str], message: str, *, env: dict[str, str] | None) -> list[str]:
        commands = [
            self._git_command(["add", *(str(relative_path) for relative_path in relative_paths)]),
            self._git_command(["commit", "-m", message]),
        ]
        return self._run_git_sequence(commands, env=env)

    def _run_git_sequence(self, commands: list[list[str]], *, env: dict[str, str] | None) -> list[str]:
        warnings: list[str] = []
        for command in commands:
            try:
                self.command_runner(
                    command,
                    cwd=self.path,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                warning = f"{self._command_label(command)} failed: {self._git_error_message(exc)}"
                warnings.append(warning)
                logger.warning("Community catalog git command failed: %s", warning)
                break
        return warnings

    def _git_author_env(self) -> dict[str, str] | None:
        if not (self.author_name or self.author_email):
            return None
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": self.author_name or "Grocy Ultimate Lookup",
                "GIT_AUTHOR_EMAIL": self.author_email or "grocy-lookup@example.local",
                "GIT_COMMITTER_NAME": self.author_name or "Grocy Ultimate Lookup",
                "GIT_COMMITTER_EMAIL": self.author_email or "grocy-lookup@example.local",
            }
        )
        return env

    def _sync_checkout(self) -> list[str]:
        if not self.repository_url:
            return []

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if (self.path / ".git").exists():
                checkout_remote_url = self._checkout_remote_url()
                if checkout_remote_url and checkout_remote_url != self.repository_url:
                    shutil.rmtree(self.path)
                    self._clone_checkout()
                    return []
                try:
                    self.command_runner(
                        self._git_command(["fetch", self.git_remote, self.git_branch]),
                        cwd=self.path,
                        env=self._git_env(),
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as exc:
                    if self._remote_branch_missing(exc):
                        shutil.rmtree(self.path)
                        self._clone_checkout()
                        return []
                    raise
                self.command_runner(
                    self._git_command(["reset", "--hard", f"{self.git_remote}/{self.git_branch}"]),
                    cwd=self.path,
                    env=self._git_env(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return []

            if self.path.exists():
                shutil.rmtree(self.path)

            self._clone_checkout()
            return []
        except Exception as exc:
            warning = f"catalog checkout sync failed: {self._git_error_message(exc)}"
            logger.warning("Community catalog checkout sync failed: %s", warning)
            return [warning]

    def sync_checkout(self) -> list[str]:
        return self._sync_checkout()

    def _clone_checkout(self) -> None:
        self.command_runner(
            self._git_command(["clone", self.repository_url, str(self.path)]),
            env=self._git_env(),
            check=True,
            capture_output=True,
            text=True,
        )
        self._checkout_branch()

    def _checkout_branch(self) -> None:
        try:
            self.command_runner(
                self._git_command(["checkout", self.git_branch]),
                cwd=self.path,
                env=self._git_env(),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            self.command_runner(
                self._git_command(["checkout", "-B", self.git_branch]),
                cwd=self.path,
                env=self._git_env(),
                check=True,
                capture_output=True,
                text=True,
            )

    def _git_command(self, args: list[str]) -> list[str]:
        return ["git", *args]

    def _checkout_remote_url(self) -> str | None:
        config_path = self.path / ".git" / "config"
        if not config_path.exists():
            return None
        parser = configparser.ConfigParser()
        parser.read(config_path)
        section = f'remote "{self.git_remote}"'
        if not parser.has_option(section, "url"):
            return None
        return parser.get(section, "url").strip()

    def _git_env(self, base: dict[str, str] | None = None) -> dict[str, str] | None:
        if not self.github_pat:
            return base
        env = dict(base) if base is not None else os.environ.copy()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {self._github_basic_token()}",
            }
        )
        return env

    def _github_basic_token(self) -> str:
        return b64encode(f"x-access-token:{self.github_pat}".encode()).decode()

    def _command_label(self, command: list[str]) -> str:
        return " ".join("<redacted>" if self.github_pat and self.github_pat in part else part for part in command)

    def _git_error_message(self, exc: Exception) -> str:
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout
            if detail:
                return detail
        return str(exc)

    def _remote_branch_missing(self, exc: subprocess.CalledProcessError) -> bool:
        detail = self._git_error_message(exc).lower()
        return (
            "couldn't find remote ref" in detail
            or "could not find remote ref" in detail
            or "couldn't find remote branch" in detail
            or "remote branch" in detail and "not found" in detail
        )

    def pending_changes(self) -> tuple[bool, str, list[str]]:
        if not (self.path / ".git").exists():
            return False, "checkout is not ready", []
        result = self.command_runner(
            self._git_command(["status", "--porcelain", "--untracked-files=all"]),
            cwd=self.path,
            env=self._git_env(),
            check=True,
            capture_output=True,
            text=True,
        )
        files = [line[3:] for line in result.stdout.splitlines() if len(line) > 3]
        return bool(files), result.stdout, files

    def pending_products(self) -> list[dict]:
        pending, _status, files = self.pending_changes()
        if not pending:
            return []
        grouped: dict[str, dict] = {}
        for file_path in files:
            product_dirs = self._pending_product_dirs(file_path)
            if not product_dirs:
                continue
            for product_dir in product_dirs:
                barcode = product_dir.name
                entry = grouped.setdefault(
                    barcode,
                    {
                        "barcode": barcode,
                        "path": product_dir.as_posix(),
                        "name": None,
                        "brand": None,
                        "quantity": None,
                        "has_image": False,
                        "files": [],
                    },
                )
                if file_path not in entry["files"]:
                    entry["files"].append(file_path)

        for entry in grouped.values():
            product_json = self.path / entry["path"] / "product.json"
            if product_json.exists():
                try:
                    payload = json.loads(product_json.read_text())
                except Exception:
                    payload = {}
                entry["name"] = payload.get("name")
                entry["brand"] = payload.get("brand")
                entry["quantity"] = payload.get("quantity") or payload.get("size")
            entry["has_image"] = (self.path / entry["path"] / "image.jpg").exists() or any(
                file_path.endswith("/image.jpg") for file_path in entry["files"]
            )
        return sorted(grouped.values(), key=lambda item: item["barcode"])

    def push_pending_changes(self) -> list[str]:
        commit_paths: list[Path | str] = ["products"]
        if self.repository_url and self._ensure_readme():
            commit_paths.append("README.md")
        if self.repository_url and self._ensure_catalog_manifest():
            commit_paths.append(CATALOG_MANIFEST)
        warnings = self._commit_paths(commit_paths, "Add confirmed products", env=self._git_env(self._git_author_env()))
        if warnings:
            return warnings
        return self._run_git_sequence(
            [self._git_command(["push", self.git_remote, self.git_branch])],
            env=self._git_env(self._git_author_env()),
        )

    def push_pending_products(self, barcodes: list[str]) -> list[str]:
        product_paths = self._selected_product_paths(barcodes)
        if not product_paths:
            return ["No selected pending products"]
        return self.commit_and_push_paths(list(product_paths), "Add confirmed products")

    def commit_and_push_paths(self, paths: list[Path | str], message: str) -> list[str]:
        if not paths:
            return ["No selected pending products"]
        commit_paths: list[Path | str] = list(paths)
        if self.repository_url and self._ensure_readme():
            commit_paths.append("README.md")
        if self.repository_url and self._ensure_catalog_manifest():
            commit_paths.append(CATALOG_MANIFEST)
        warnings = self._commit_paths(commit_paths, message, env=self._git_env(self._git_author_env()))
        if warnings:
            return warnings
        return self._run_git_sequence(
            [self._git_command(["push", self.git_remote, self.git_branch])],
            env=self._git_env(self._git_author_env()),
        )

    def discard_pending_changes(self) -> list[str]:
        commands = [
            self._git_command(["reset", "--hard", "HEAD"]),
            self._git_command(["clean", "-fd", "products"]),
        ]
        return self._run_git_sequence(commands, env=None)

    def discard_pending_products(self, barcodes: list[str]) -> list[str]:
        product_paths = self._selected_product_paths(barcodes)
        if not product_paths:
            return ["No selected pending products"]
        warnings: list[str] = []
        for product_path in product_paths:
            restore = self.command_runner(
                self._git_command(["restore", "--", str(product_path)]),
                cwd=self.path,
                env=None,
                check=False,
                capture_output=True,
                text=True,
            )
            if restore.returncode not in {0, 1}:
                warnings.append(f"git restore {product_path} failed: {self._completed_error_message(restore)}")
                break
            clean = self.command_runner(
                self._git_command(["clean", "-fd", "--", str(product_path)]),
                cwd=self.path,
                env=None,
                check=False,
                capture_output=True,
                text=True,
            )
            if clean.returncode != 0:
                warnings.append(f"git clean {product_path} failed: {self._completed_error_message(clean)}")
                break
        return warnings

    def _pending_product_dirs(self, file_path: str) -> list[Path]:
        path = Path(file_path)
        parts = path.parts
        if len(parts) < 2 or parts[0] != "products":
            return []
        if len(parts) >= 4:
            return [Path(*parts[:4])]
        root = self.path / path
        if not root.exists():
            return []
        product_dirs: list[Path] = []
        for product_json in root.glob("*/*/product.json"):
            try:
                product_dirs.append(product_json.parent.relative_to(self.path))
            except ValueError:
                continue
        return sorted(product_dirs)

    def _selected_product_paths(self, barcodes: list[str]) -> list[Path]:
        selected = {sanitize_barcode(barcode) for barcode in barcodes}
        pending = self.pending_products()
        paths: list[Path] = []
        for product in pending:
            if product["barcode"] in selected:
                paths.append(Path(product["path"]))
        return paths

    @staticmethod
    def _completed_error_message(result: subprocess.CompletedProcess[str]) -> str:
        return (result.stderr or result.stdout or "").strip()


class RuntimeCommunityCatalogExporter:
    def __init__(self, settings_store, queue_store=None) -> None:
        self.settings_store = settings_store
        self.queue_store = queue_store

    def export_confirmed_product(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
    ) -> CommunityCatalogExportResult:
        current = self.settings_store.get_community_catalog()
        if not current.enabled:
            return CommunityCatalogExportResult(exported=False)
        local_image_path = self._local_uploaded_image_path(product)
        if current.repository_url and not current.auto_push:
            self._queue().upsert(barcode, product, local_image_path=str(local_image_path) if local_image_path else None)
            return CommunityCatalogExportResult(exported=True)

        exporter = self._exporter(current)
        result = exporter.export_confirmed_product(barcode, product, local_image_path=local_image_path)
        if result.warnings:
            self._queue().upsert(barcode, product, local_image_path=str(local_image_path) if local_image_path else None)
        return result

    def pending_products(self) -> list[dict]:
        return [self._public_pending_item(item) for item in self._queue().list()]

    def push_pending_products(self, barcodes: list[str]) -> list[str]:
        current = self.settings_store.get_community_catalog()
        queued = self._queue().selected(barcodes)
        if not queued:
            return ["No selected pending products"]
        exporter = self._exporter(current, auto_push=False, auto_commit=False)
        warnings = exporter.sync_checkout()
        if warnings:
            return warnings
        product_paths: list[Path] = []
        pushed_barcodes: list[str] = []
        for item in queued:
            result = exporter.export_confirmed_product(
                item["barcode"],
                item["product"],
                local_image_path=item["local_image_path"],
                sync_checkout=False,
            )
            if result.warnings:
                return list(result.warnings)
            product_paths.append(catalog_product_dir(item["barcode"]))
            pushed_barcodes.append(item["barcode"])
        warnings = exporter.commit_and_push_paths(product_paths, "Add confirmed products")
        if warnings:
            return warnings
        self._queue().delete(pushed_barcodes)
        return []

    def discard_pending_products(self, barcodes: list[str]) -> list[str]:
        self._queue().delete(barcodes)
        return []

    def _exporter(self, current, *, auto_push: bool | None = None, auto_commit: bool | None = None) -> CommunityCatalogExporter:
        return CommunityCatalogExporter(
            path=current.workdir if current.repository_url else current.path,
            enabled=current.enabled,
            export_images=current.export_images,
            auto_commit=current.auto_commit if auto_commit is None else auto_commit,
            auto_push=current.auto_push if auto_push is None else auto_push,
            git_remote=current.git_remote,
            git_branch=current.git_branch,
            repository_url=current.repository_url,
            github_pat=current.github_pat,
            branch=current.branch,
            author_name=current.author_name,
            author_email=current.author_email,
            uploaded_images_path=settings.uploaded_images_path,
            uploaded_images_base_url=settings.uploaded_images_base_url,
        )

    def _queue(self):
        if self.queue_store is None:
            from app.community_catalog_queue import CommunityCatalogQueue

            self.queue_store = CommunityCatalogQueue(settings.community_catalog_queue_path)
        return self.queue_store

    def _local_uploaded_image_path(self, product: ConfirmedProductRequest) -> Path | None:
        if product.image_url is None:
            return None
        exporter = self._exporter(self.settings_store.get_community_catalog())
        image_url = str(product.image_url)
        if not exporter._is_uploaded_image_url(image_url):
            return None
        return Path(settings.uploaded_images_path) / exporter._uploaded_image_name(image_url)

    @staticmethod
    def _public_pending_item(item: dict) -> dict:
        return {key: value for key, value in item.items() if key not in {"product", "local_image_path"}}


class CommunityCatalogSourceRegistry:
    def __init__(self, settings_store, *, command_runner: CommandRunner | None = None) -> None:
        self.settings_store = settings_store
        self.command_runner = command_runner or subprocess.run

    def get_sources(self) -> CommunityCatalogSourceList:
        saved = self.settings_store.get_community_catalog_sources()
        refreshed = [self._refresh_source_if_stale(source) for source in saved.sources]
        result = CommunityCatalogSourceList(sources=refreshed)
        self.settings_store.set_community_catalog_sources(result)
        return result

    def validate_and_store_sources(self, value: CommunityCatalogSourceList) -> CommunityCatalogSourceList:
        validated = [self._validated_source(source, reject_invalid=True) for source in value.sources]
        return self.settings_store.set_community_catalog_sources(CommunityCatalogSourceList(sources=validated))

    def refresh_source(self, source_id: str) -> CommunityCatalogSource:
        saved = self.settings_store.get_community_catalog_sources()
        refreshed: list[CommunityCatalogSource] = []
        selected: CommunityCatalogSource | None = None
        for source in saved.sources:
            if source.id == source_id:
                source = self._validated_source(source)
                selected = source
            refreshed.append(source)
        self.settings_store.set_community_catalog_sources(CommunityCatalogSourceList(sources=refreshed))
        if selected is None:
            raise ValueError("Catalog source not found")
        return selected

    def _refresh_source_if_stale(self, source: CommunityCatalogSource) -> CommunityCatalogSource:
        if self._is_stale(source):
            return self._validated_source(source)
        return source

    def _validated_source(self, source: CommunityCatalogSource, *, reject_invalid: bool = False) -> CommunityCatalogSource:
        result = self.validate_source(source)
        if reject_invalid and result.status == "invalid":
            raise ValueError(result.message)
        return source.model_copy(
            update={
                "owner": result.owner,
                "description": result.description,
                "product_count": result.product_count,
                "validation_status": result.status,
                "validation_message": result.message,
                "warnings": list(result.warnings),
                "last_checked": result.last_checked,
                "last_successful_check": result.last_successful_check,
                "last_failed_check": result.last_failed_check,
                "last_error": result.last_error,
            }
        )

    def validate_source(self, source: CommunityCatalogSource) -> CatalogValidationResult:
        checkout = self._checkout_path(source)
        current = self.settings_store.get_community_catalog()
        exporter = CommunityCatalogExporter(
            path=checkout,
            enabled=True,
            repository_url=source.repository_url,
            github_pat=current.github_pat,
            branch="main",
            author_name=current.author_name,
            author_email=current.author_email,
            command_runner=self.command_runner,
        )
        warnings = exporter.sync_checkout()
        checked_at = datetime.now(UTC).isoformat()
        if warnings:
            message = "; ".join(warnings)
            return CatalogValidationResult(
                status=self._status_for_sync_error(message),
                message=message,
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=message,
            )
        manifest_path = checkout / CATALOG_MANIFEST
        if not manifest_path.exists():
            return CatalogValidationResult(
                status="invalid_manifest",
                message=f"{CATALOG_MANIFEST} is required",
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=f"{CATALOG_MANIFEST} is required",
            )
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception as exc:
            message = f"{CATALOG_MANIFEST} is not valid JSON: {exc}"
            return CatalogValidationResult(
                status="invalid_manifest",
                message=message,
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=message,
            )
        if manifest.get("type") != CATALOG_TYPE:
            message = f"{CATALOG_MANIFEST} type must be {CATALOG_TYPE}"
            return CatalogValidationResult(
                status="invalid_manifest",
                message=message,
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=message,
            )
        if manifest.get("schema_version") != CATALOG_SCHEMA_VERSION:
            message = f"{CATALOG_MANIFEST} schema_version must be {CATALOG_SCHEMA_VERSION}"
            return CatalogValidationResult(
                status="invalid_manifest",
                message=message,
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=message,
            )
        products_dir = checkout / "products"
        if not products_dir.is_dir():
            message = "products directory is missing"
            return CatalogValidationResult(
                status="invalid_manifest",
                message=message,
                owner=self._text_value(manifest.get("owner")),
                description=self._text_value(manifest.get("description")),
                last_checked=checked_at,
                last_failed_check=checked_at,
                last_error=message,
            )
        product_count = len(list(products_dir.glob("*/*/*/product.json")))
        warning_list: list[str] = []
        status = "valid"
        message = "Catalog source is ready"
        if product_count == 0:
            status = "valid_with_warnings"
            message = "Catalog source is empty"
            warning_list.append("No product.json files found under products/")
        return CatalogValidationResult(
            status=status,
            message=message,
            owner=self._text_value(manifest.get("owner")),
            description=self._text_value(manifest.get("description")),
            product_count=product_count,
            warnings=tuple(warning_list),
            last_checked=checked_at,
            last_successful_check=checked_at,
        )

    def _checkout_root(self) -> Path:
        current = self.settings_store.get_community_catalog()
        return Path(current.workdir).parent / "community-catalog-sources"

    def _checkout_path(self, source: CommunityCatalogSource) -> Path:
        source_id = source.id or "".join(char if char.isalnum() else "-" for char in source.repository_url.lower()).strip("-")
        return self._checkout_root() / (source_id or "source")

    @staticmethod
    def _text_value(value) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _status_for_sync_error(message: str) -> str:
        detail = message.lower()
        if "authentication failed" in detail or "not found" in detail and "repository" in detail:
            return "invalid_auth"
        if "could not resolve host" in detail or "timed out" in detail or "connection" in detail:
            return "unreachable"
        return "checkout_failed"

    @staticmethod
    def _is_stale(source: CommunityCatalogSource) -> bool:
        if not source.last_checked:
            return True
        try:
            checked_at = datetime.fromisoformat(source.last_checked)
        except ValueError:
            return True
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - checked_at >= SOURCE_STATUS_TTL


def exporter_from_settings(current, *, command_runner: CommandRunner | None = None) -> CommunityCatalogExporter:
    return CommunityCatalogExporter(
        path=current.workdir if current.repository_url else current.path,
        enabled=current.enabled,
        export_images=current.export_images,
        auto_commit=current.auto_commit,
        auto_push=current.auto_push,
        git_remote=current.git_remote,
        git_branch=current.git_branch,
        repository_url=current.repository_url,
        github_pat=current.github_pat,
        branch=current.branch,
        author_name=current.author_name,
        author_email=current.author_email,
        uploaded_images_path=settings.uploaded_images_path,
        uploaded_images_base_url=settings.uploaded_images_base_url,
        command_runner=command_runner,
    )
