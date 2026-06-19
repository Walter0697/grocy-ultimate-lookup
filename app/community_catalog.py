from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.models import ConfirmedProductRequest

logger = logging.getLogger(__name__)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

CATALOG_README = """# Grocy Community Catalog

Welcome. This repository is a product catalog created by Grocy Ultimate Lookup.

Products are stored by barcode under the `products/` directory. Each product folder can contain a `product.json` file and, when image export is enabled, an `image.jpg` file.

This catalog can be produced by connecting your own product scanning workflow to Grocy Ultimate Lookup and confirming products as you scan them.

See [Grocy Ultimate Lookup](https://github.com/Walter0697/grocy-ultimate-lookup) for how the catalog format works and how to run the lookup service.
"""


@dataclass(frozen=True)
class CommunityCatalogExportResult:
    exported: bool
    product_json_path: Path | None = None
    warnings: tuple[str, ...] = ()


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
        self.command_runner = command_runner or subprocess.run

    def export_confirmed_product(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
    ) -> CommunityCatalogExportResult:
        if not self.enabled:
            return CommunityCatalogExportResult(exported=False)

        warnings: list[str] = []
        if self.repository_url:
            warnings.extend(self._sync_checkout())
            if warnings:
                return CommunityCatalogExportResult(exported=False, warnings=tuple(warnings))

        product_dir = self.path / catalog_product_dir(barcode)
        product_dir.mkdir(parents=True, exist_ok=True)
        product_json_path = product_dir / "product.json"
        payload = self._product_payload(barcode, product)
        product_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

        if self.export_images and product.image_url is not None:
            try:
                self._download_image(str(product.image_url), product_dir / "image.jpg")
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

    def _product_payload(self, barcode: str, product: ConfirmedProductRequest) -> dict:
        return {
            "schema_version": 1,
            "barcode": barcode,
            "name": product.name.strip(),
            "brand": product.brand,
            "quantity": product.quantity,
            "size": product.size,
            "count": product.count,
            "variant": product.variant,
            "image_url": str(product.image_url) if product.image_url is not None else None,
            "notes": product.notes,
            "source": "user_confirmed",
            "confirmed_at": datetime.now(UTC).isoformat(),
        }

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
                warning = f"{self._command_label(command)} failed: {exc}"
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
                self.command_runner(
                    self._git_command(["fetch", self.git_remote, self.git_branch]),
                    cwd=self.path,
                    env=self._git_env(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
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

            self.command_runner(
                self._git_command(["clone", self.repository_url, str(self.path)]),
                env=self._git_env(),
                check=True,
                capture_output=True,
                text=True,
            )
            self._checkout_branch()
            return []
        except Exception as exc:
            warning = f"catalog checkout sync failed: {exc}"
            logger.warning("Community catalog checkout sync failed: %s", exc)
            return [warning]

    def sync_checkout(self) -> list[str]:
        return self._sync_checkout()

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

    def _git_env(self, base: dict[str, str] | None = None) -> dict[str, str] | None:
        if not self.github_pat:
            return base
        env = dict(base) if base is not None else os.environ.copy()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {self.github_pat}",
            }
        )
        return env

    def _command_label(self, command: list[str]) -> str:
        return " ".join("<redacted>" if self.github_pat and self.github_pat in part else part for part in command)

    def pending_changes(self) -> tuple[bool, str, list[str]]:
        if not (self.path / ".git").exists():
            return False, "checkout is not ready", []
        result = self.command_runner(
            self._git_command(["status", "--porcelain"]),
            cwd=self.path,
            env=self._git_env(),
            check=True,
            capture_output=True,
            text=True,
        )
        files = [line[3:] for line in result.stdout.splitlines() if len(line) > 3]
        return bool(files), result.stdout, files

    def push_pending_changes(self) -> list[str]:
        warnings = self._commit_path("products", "Add confirmed products", env=self._git_env(self._git_author_env()))
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


class RuntimeCommunityCatalogExporter:
    def __init__(self, settings_store) -> None:
        self.settings_store = settings_store

    def export_confirmed_product(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
    ) -> CommunityCatalogExportResult:
        current = self.settings_store.get_community_catalog()
        exporter = CommunityCatalogExporter(
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
        )
        return exporter.export_confirmed_product(barcode, product)


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
        command_runner=command_runner,
    )
