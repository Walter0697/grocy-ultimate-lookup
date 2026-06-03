from app.local_store import LocalProductStore
from app.models import ConfirmedProductRequest


def test_local_product_store_upserts_and_returns_confirmed_product(tmp_path) -> None:
    store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    product = store.upsert(
        "810669032478",
        ConfirmedProductRequest(
            name="Kitchen Box Item",
            brand="Kitchen Brand",
            quantity="1 box",
            notes="added manually",
        ),
    )

    assert product.barcode == "810669032478"
    assert product.user_product_name == "Kitchen Box Item"
    assert product.brand == "Kitchen Brand"
    assert product.quantity == "1 box"
    assert product.notes == "added manually"
    assert product.created_at == product.updated_at


def test_local_product_store_correction_updates_existing_product(tmp_path) -> None:
    store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    store.upsert("810669032478", ConfirmedProductRequest(name="Old Name"))

    corrected = store.upsert("810669032478", ConfirmedProductRequest(name="Corrected Name", count=6))

    assert corrected.user_product_name == "Corrected Name"
    assert corrected.count == 6


def test_local_product_store_converts_confirmed_product_to_lookup_result(tmp_path) -> None:
    store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    product = store.upsert(
        "067489302124",
        ConfirmedProductRequest(name="Confirmed Product 12 oz", brand="Confirmed Brand"),
    )

    result = store.to_lookup_result(product)

    assert result.barcode == "067489302124"
    assert result.name == "Confirmed Product 12 oz"
    assert result.normalized_name == "Confirmed Product"
    assert result.brand == "Confirmed Brand"
    assert result.size == "12 oz"
    assert result.source == "local_confirmed"
    assert result.confidence == 1.0


def test_local_product_store_deletes_confirmed_product(tmp_path) -> None:
    store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    store.upsert("067489302124", ConfirmedProductRequest(name="Confirmed Product"))

    assert store.delete("067489302124") is True
    assert store.get("067489302124") is None
    assert store.delete("067489302124") is False
