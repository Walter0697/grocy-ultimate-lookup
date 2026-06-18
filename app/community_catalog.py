from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models import ConfirmedProductRequest

logger = logging.getLogger(__name__)


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
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.export_images = export_images
        self.auto_commit = auto_commit
        self.auto_push = auto_push
        self.git_remote = git_remote
        self.git_branch = git_branch
        self.author_name = author_name
        self.author_email = author_email

    def export_confirmed_product(
        self,
        barcode: str,
        product: ConfirmedProductRequest,
    ) -> CommunityCatalogExportResult:
        if not self.enabled:
            return CommunityCatalogExportResult(exported=False)

        product_dir = self.path / catalog_product_dir(barcode)
        product_dir.mkdir(parents=True, exist_ok=True)
        product_json_path = product_dir / "product.json"
        payload = self._product_payload(barcode, product)
        product_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

        warnings: list[str] = []
        if self.export_images and product.image_url is not None:
            try:
                self._download_image(str(product.image_url), product_dir / "image.jpg")
            except Exception as exc:
                warnings.append(f"image export failed: {exc}")
                logger.warning("Community catalog image export failed for %s: %s", barcode, exc)

        if self.auto_commit:
            warnings.extend(self._commit_and_maybe_push(product_json_path, barcode))

        return CommunityCatalogExportResult(
            exported=True,
            product_json_path=product_json_path,
            warnings=tuple(warnings),
        )

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
        commit_message = f"Add product {barcode}"
        commands = [
            ["git", "add", str(relative_product_dir)],
            ["git", "commit", "-m", commit_message],
        ]
        if self.auto_push:
            commands.append(["git", "push", self.git_remote, self.git_branch])

        env = None
        if self.author_name or self.author_email:
            env = os.environ.copy()
            env.update(
                {
                "GIT_AUTHOR_NAME": self.author_name or "Grocy Ultimate Lookup",
                "GIT_AUTHOR_EMAIL": self.author_email or "grocy-lookup@example.local",
                "GIT_COMMITTER_NAME": self.author_name or "Grocy Ultimate Lookup",
                "GIT_COMMITTER_EMAIL": self.author_email or "grocy-lookup@example.local",
                }
            )

        for command in commands:
            try:
                subprocess.run(
                    command,
                    cwd=self.path,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                warning = f"{' '.join(command)} failed: {exc}"
                warnings.append(warning)
                logger.warning("Community catalog git command failed: %s", warning)
                break
        return warnings
