from app.auto_created_store import AutoCreatedProductStore


def test_auto_created_store_upserts_and_reads_product(tmp_path) -> None:
    store = AutoCreatedProductStore(str(tmp_path / "auto-created.sqlite3"))

    store.upsert(product_id=22, barcode="123456", source="open_food_facts")

    assert store.get_by_product_id(22) == {
        "product_id": 22,
        "barcode": "123456",
        "source": "open_food_facts",
    }


def test_auto_created_store_deletes_product(tmp_path) -> None:
    store = AutoCreatedProductStore(str(tmp_path / "auto-created.sqlite3"))
    store.upsert(product_id=22, barcode="123456", source="open_food_facts")

    assert store.delete(22) is True
    assert store.get_by_product_id(22) is None
