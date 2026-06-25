import base64
import json

import httpx

from app.adapters.community_catalog import CommunityCatalogAdapter, parse_github_repository_url
from app.config import settings
from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogSettings,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
)


def github_content_response(payload: dict) -> httpx.Response:
    content = base64.b64encode(json.dumps(payload).encode()).decode()
    return httpx.Response(200, json={"encoding": "base64", "content": content})


def github_file_response(content: bytes = b"image") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(content).decode(),
        },
    )


def store_with_source(tmp_path, *, github_pat: str | None) -> AppSettingsStore:
    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=True,
            repository_url="https://github.com/example/my-catalog.git",
            github_pat=github_pat,
            branch="main",
            workdir=str(tmp_path / "workdir"),
            path=str(tmp_path / "catalog"),
            export_images=True,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name=None,
            author_email=None,
        ),
    )
    store.set_community_catalog_sources(
        CommunityCatalogSourceList(
            sources=[
                CommunityCatalogSource(
                    name="Private catalog",
                    repository_url="https://github.com/example/private-catalog.git",
                    enabled=True,
                )
            ]
        )
    )
    return store


async def run_lookup(tmp_path, *, github_pat: str | None, seen_requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return github_content_response(
            {
                "schema_version": 1,
                "barcode": "627985000070",
                "name": "Catalog Product",
                "brand": "Catalog Brand",
                "quantity": "500 mL",
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CommunityCatalogAdapter(store_with_source(tmp_path, github_pat=github_pat), client=client)
    try:
        return await adapter.lookup("627985000070")
    finally:
        await client.aclose()


def test_parse_github_repository_url_supports_https_and_ssh() -> None:
    assert parse_github_repository_url("https://github.com/example/catalog.git").owner == "example"
    assert parse_github_repository_url("git@github.com:example/catalog.git").repo == "catalog"
    assert parse_github_repository_url("https://gitlab.com/example/catalog.git") is None


def test_community_catalog_adapter_uses_saved_pat_for_github_api(tmp_path) -> None:
    import asyncio

    seen_requests: list[httpx.Request] = []

    result = asyncio.run(run_lookup(tmp_path, github_pat="secret-token", seen_requests=seen_requests))

    assert result.name == "Catalog Product"
    assert result.brand == "Catalog Brand"
    assert result.source == "community_catalog"
    assert seen_requests[0].headers["Authorization"] == "Bearer secret-token"
    assert str(seen_requests[0].url) == (
        "https://api.github.com/repos/example/private-catalog/contents/"
        "products/627/985/627985000070/product.json?ref=main"
    )


def test_community_catalog_adapter_omits_authorization_without_pat(tmp_path) -> None:
    import asyncio

    seen_requests: list[httpx.Request] = []

    asyncio.run(run_lookup(tmp_path, github_pat=None, seen_requests=seen_requests))

    assert "Authorization" not in seen_requests[0].headers


def test_community_catalog_adapter_copies_sibling_catalog_image_to_uploaded_images(tmp_path, monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(settings, "uploaded_images_base_url", "http://lookup.test/uploaded-images")
    monkeypatch.setattr(settings, "uploaded_images_path", str(tmp_path / "uploaded-images"))
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if str(request.url).endswith("/product.json?ref=main"):
            return github_content_response(
                {
                    "schema_version": 1,
                    "barcode": "627985000070",
                    "name": "Catalog Product",
                    "image_url": "http://host.docker.internal:9290/uploaded-images/stale-local-image.jpg",
                }
            )
        if str(request.url).endswith("/image.jpg?ref=main"):
            return github_file_response(b"catalog-image")
        return httpx.Response(404)

    store = store_with_source(tmp_path, github_pat="secret-token")
    source_id = store.get_community_catalog_sources().sources[0].id
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CommunityCatalogAdapter(store, client=client)
    try:
        result = asyncio.run(adapter.lookup("627985000070"))
    finally:
        asyncio.run(client.aclose())

    assert str(result.image_url) == f"http://lookup.test/uploaded-images/catalog-{source_id}-627985000070.jpg"
    assert (tmp_path / "uploaded-images" / f"catalog-{source_id}-627985000070.jpg").read_bytes() == b"catalog-image"
    assert len(seen_requests) == 2
    assert seen_requests[1].headers["Authorization"] == "Bearer secret-token"


def test_community_catalog_adapter_keeps_external_payload_image_url(tmp_path) -> None:
    import asyncio

    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return github_content_response(
            {
                "schema_version": 1,
                "barcode": "627985000070",
                "name": "Catalog Product",
                "image_url": "https://cdn.example.test/product.jpg",
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CommunityCatalogAdapter(store_with_source(tmp_path, github_pat=None), client=client)
    try:
        result = asyncio.run(adapter.lookup("627985000070"))
    finally:
        asyncio.run(client.aclose())

    assert str(result.image_url) == "https://cdn.example.test/product.jpg"
    assert len(seen_requests) == 1


def test_community_catalog_adapter_skips_invalid_sources(tmp_path) -> None:
    import asyncio

    store = AppSettingsStore(
        str(tmp_path / "settings.sqlite3"),
        community_catalog_defaults=CommunityCatalogSettings(
            enabled=True,
            repository_url="https://github.com/example/my-catalog.git",
            github_pat=None,
            branch="main",
            workdir=str(tmp_path / "workdir"),
            path=str(tmp_path / "catalog"),
            export_images=True,
            auto_commit=False,
            auto_push=False,
            git_remote="origin",
            git_branch="main",
            author_name=None,
            author_email=None,
        ),
    )
    store.set_community_catalog_sources(
        CommunityCatalogSourceList(
            sources=[
                CommunityCatalogSource(
                    name="Invalid catalog",
                    repository_url="https://github.com/example/invalid-catalog.git",
                    enabled=True,
                    validation_status="invalid",
                ),
                CommunityCatalogSource(
                    name="Valid catalog",
                    repository_url="https://github.com/example/valid-catalog.git",
                    enabled=True,
                    validation_status="valid",
                ),
            ]
        )
    )
    seen_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(str(request.url))
        return github_content_response(
            {
                "schema_version": 1,
                "barcode": "627985000070",
                "name": "Catalog Product",
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CommunityCatalogAdapter(store, client=client)
    try:
        result = asyncio.run(adapter.lookup("627985000070"))
    finally:
        asyncio.run(client.aclose())

    assert result is not None
    assert all("/repos/example/valid-catalog/" in request for request in seen_requests)
    assert all("/repos/example/invalid-catalog/" not in request for request in seen_requests)
