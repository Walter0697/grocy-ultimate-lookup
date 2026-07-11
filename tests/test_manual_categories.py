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
