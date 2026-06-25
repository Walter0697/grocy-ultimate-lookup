from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from app.adapters.base import LookupAdapter
from app.app_settings import AppSettingsStore, CommunityCatalogSource
from app.community_catalog import catalog_product_dir
from app.config import settings
from app.models import LookupResult


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    repo: str


class CommunityCatalogAdapter(LookupAdapter):
    name = "community_catalog"

    def __init__(
        self,
        settings_store: AppSettingsStore | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings_store = settings_store or AppSettingsStore(settings.app_settings_path)
        self.client = client

    async def lookup(self, barcode: str) -> LookupResult | None:
        sources = self.settings_store.get_community_catalog_sources().sources
        enabled_sources = sorted(
            (
                source
                for source in sources
                if source.enabled and source.validation_status in {None, "valid", "valid_with_warnings"}
            ),
            key=lambda source: source.priority,
        )
        if not enabled_sources:
            return None

        github_pat = self.settings_store.get_community_catalog().github_pat
        if self.client is not None:
            for source in enabled_sources:
                result = await self._lookup_source(barcode, source, github_pat, self.client)
                if result is not None:
                    return result
            return None

        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds) as client:
            for source in enabled_sources:
                result = await self._lookup_source(barcode, source, github_pat, client)
                if result is not None:
                    return result
        return None

    async def _lookup_source(
        self,
        barcode: str,
        source: CommunityCatalogSource,
        github_pat: str | None,
        client: httpx.AsyncClient,
    ) -> LookupResult | None:
        repo = parse_github_repository_url(source.repository_url)
        if repo is None:
            return None

        product_dir = catalog_product_dir(barcode)
        product_path = product_dir / "product.json"
        url = github_contents_url(repo, product_path.as_posix())
        try:
            response = await client.get(url, headers=github_headers(github_pat))
        except httpx.HTTPError:
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            return None

        try:
            payload = decode_github_contents_json(response.json())
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            return None

        image_url = external_payload_image_url(payload.get("image_url")) or await self._catalog_image_url(
            repo,
            product_dir / "image.jpg",
            source.id,
            barcode,
            github_pat,
            client,
        )

        return LookupResult(
            barcode=barcode,
            name=name.strip(),
            brand=payload.get("brand"),
            quantity=payload.get("quantity"),
            size=payload.get("size"),
            count=payload.get("count"),
            variant=payload.get("variant"),
            image_url=image_url,
            source=self.name,
            confidence=0.92,
            raw_url=url,
            raw_payload={
                "catalog_source": source.model_dump(mode="json"),
                "product": payload,
                "barcode_verified": payload.get("barcode") == barcode,
            },
        )

    async def _catalog_image_url(
        self,
        repo: GitHubRepository,
        image_path,
        source_id: str | None,
        barcode: str,
        github_pat: str | None,
        client: httpx.AsyncClient,
    ) -> str | None:
        if not source_id:
            return None
        url = github_contents_url(repo, image_path.as_posix())
        try:
            response = await client.get(url, headers=github_headers(github_pat))
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return None
        if payload.get("type") != "file":
            return None
        try:
            content = base64.b64decode(str(payload["content"]))
        except (KeyError, TypeError, ValueError):
            return None
        return save_catalog_image(source_id, barcode, content)


def parse_github_repository_url(repository_url: str) -> GitHubRepository | None:
    value = repository_url.strip()
    patterns = [
        r"^https://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
        r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return GitHubRepository(owner=match.group(1), repo=match.group(2))
    return None


def github_contents_url(repo: GitHubRepository, path: str) -> str:
    encoded_path = "/".join(quote(part) for part in path.split("/"))
    return f"https://api.github.com/repos/{repo.owner}/{repo.repo}/contents/{encoded_path}?ref=main"


def github_headers(github_pat: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": settings.lookup_user_agent,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_pat:
        headers["Authorization"] = f"Bearer {github_pat}"
    return headers


def external_payload_image_url(image_url) -> str | None:
    if not isinstance(image_url, str) or not image_url.strip():
        return None
    value = image_url.strip()
    if "/uploaded-images/" in urlsplit(value).path:
        return None
    return value


def save_catalog_image(source_id: str, barcode: str, content: bytes) -> str:
    uploaded_dir = Path(settings.uploaded_images_path)
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id).strip("-") or "catalog"
    safe_barcode = re.sub(r"[^A-Za-z0-9_.-]+", "-", barcode).strip("-") or "barcode"
    file_name = f"catalog-{safe_source}-{safe_barcode}.jpg"
    (uploaded_dir / file_name).write_bytes(content)
    return f"{settings.uploaded_images_base_url.rstrip('/')}/{file_name}"


def decode_github_contents_json(payload: dict) -> dict:
    if payload.get("encoding") != "base64":
        raise ValueError("unsupported GitHub contents encoding")
    content = str(payload["content"])
    decoded = base64.b64decode(content).decode()
    return json.loads(decoded)
