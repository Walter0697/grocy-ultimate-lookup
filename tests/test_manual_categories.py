import asyncio

import httpx
import pytest

from app import main
from app.manual_category_store import ManualCategoryStore


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def manual_category_store(tmp_path, monkeypatch):
    store = ManualCategoryStore(str(tmp_path / "manual-categories.sqlite3"))
    monkeypatch.setattr(main, "manual_category_store", store)
    return store


def test_list_manual_categories_starts_empty(manual_category_store) -> None:
    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/dashboard/manual-categories")

    response = run(request())

    assert response.status_code == 200
    assert response.json() == []


def test_create_manual_category_with_emoji(manual_category_store) -> None:
    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/dashboard/manual-categories",
                json={"name": "Mango", "group": "produce", "emoji": "🥭"},
            )

    response = run(request())

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Mango"
    assert body["group"] == "produce"
    assert body["emoji"] == "🥭"
    assert body["custom"] is True
    assert body["variants"] == []
    assert body["id"].startswith("custom-")


def test_create_manual_category_with_image(manual_category_store) -> None:
    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/dashboard/manual-categories",
                json={
                    "name": "Herbs",
                    "group": "other",
                    "image_url": "/uploaded-images/herbs.jpg",
                },
            )

    response = run(request())

    assert response.status_code == 200
    body = response.json()
    assert body["image_url"] == "/uploaded-images/herbs.jpg"
    assert body["emoji"] is None


def test_create_manual_category_requires_icon(manual_category_store) -> None:
    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/dashboard/manual-categories",
                json={"name": "Mystery", "group": "other"},
            )

    response = run(request())

    assert response.status_code == 422


def test_create_manual_category_item(manual_category_store) -> None:
    category = manual_category_store.create_category(
        name="Mango",
        group="produce",
        emoji="🥭",
    )

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/dashboard/manual-categories/{category['id']}/items",
                json={
                    "name": "Ataulfo Mango",
                    "quantity": "per mango",
                    "unit": "piece",
                    "default_location": "Counter",
                    "note": "Butter mango",
                    "favorite": True,
                },
            )

    response = run(request())

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ataulfo Mango"
    assert body["category_id"] == category["id"]
    assert body["favorite"] is True
    assert body["id"].startswith("custom-item-")


def test_list_manual_category_items(manual_category_store) -> None:
    category = manual_category_store.create_category(
        name="Herbs",
        group="other",
        emoji="🌿",
    )
    manual_category_store.create_item(
        category_id=category["id"],
        name="Basil",
        quantity="per bunch",
        unit="bunch",
        default_location="Fridge",
    )

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/dashboard/manual-category-items")

    response = run(request())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Basil"


def test_create_manual_category_item_rejects_external_image(manual_category_store) -> None:
    category = manual_category_store.create_category(
        name="Herbs",
        group="other",
        emoji="🌿",
    )

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/dashboard/manual-categories/{category['id']}/items",
                json={
                    "name": "Basil",
                    "quantity": "per bunch",
                    "unit": "bunch",
                    "default_location": "Fridge",
                    "image_url": "https://example.com/basil.jpg",
                },
            )

    response = run(request())

    assert response.status_code == 422


def test_create_manual_category_item_with_lookup_image(manual_category_store) -> None:
    category = manual_category_store.create_category(
        name="Herbs",
        group="other",
        emoji="🌿",
    )

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/dashboard/manual-categories/{category['id']}/items",
                json={
                    "name": "Basil",
                    "quantity": "per bunch",
                    "unit": "bunch",
                    "default_location": "Fridge",
                    "image_url": "/uploaded-images/basil.jpg",
                },
            )

    response = run(request())

    assert response.status_code == 200
    assert response.json()["image_url"] == "/uploaded-images/basil.jpg"


def test_create_manual_category_item_triggers_catalog_export(monkeypatch, manual_category_store) -> None:
    category = manual_category_store.create_category(
        name="Herbs",
        group="other",
        emoji="🌿",
    )
    calls = []

    class Exporter:
        def export_manual_item(self, item, *, category=None):
            calls.append((item, category))
            return None

    monkeypatch.setattr(main, "community_catalog_runtime", Exporter())

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/dashboard/manual-categories/{category['id']}/items",
                json={
                    "name": "Basil",
                    "quantity": "per bunch",
                    "unit": "bunch",
                    "default_location": "Fridge",
                    "image_url": "/uploaded-images/basil.jpg",
                },
            )

    response = run(request())

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0]["name"] == "Basil"
    assert calls[0][1]["id"] == category["id"]


def test_list_community_catalog_items(monkeypatch, manual_category_store) -> None:
    class Adapter:
        def __init__(self, settings_store=None):
            pass

        async def list_items(self):
            return [
                {
                    "id": "catalog-source-herbs",
                    "name": "Herbs",
                    "group": "other",
                    "variants": [
                        {
                            "id": "catalog-source-basil",
                            "name": "Basil",
                            "quantity": "per bunch",
                            "unit": "bunch",
                        }
                    ],
                }
            ]

    monkeypatch.setattr(main, "CommunityCatalogAdapter", Adapter)

    async def request():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/dashboard/community-catalog-items")

    response = run(request())

    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Herbs"
    assert body[0]["variants"][0]["name"] == "Basil"
