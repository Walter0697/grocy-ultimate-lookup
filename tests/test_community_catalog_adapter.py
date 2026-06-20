import base64
import json

import httpx

from app.adapters.community_catalog import CommunityCatalogAdapter, parse_github_repository_url
from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogSettings,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
)


def github_content_response(payload: dict) -> httpx.Response:
    content = base64.b64encode(json.dumps(payload).encode()).decode()
    return httpx.Response(200, json={"encoding": "base64", "content": content})


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
