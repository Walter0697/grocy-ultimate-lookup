import json

from app.community_catalog import CommunityCatalogExporter, catalog_product_dir
from app.models import ConfirmedProductRequest


def test_catalog_product_dir_uses_two_three_digit_shards_and_full_barcode() -> None:
    assert catalog_product_dir("627985000070").as_posix() == "products/627/985/627985000070"
    assert catalog_product_dir("83400090029449960471").as_posix() == "products/834/000/83400090029449960471"
    assert catalog_product_dir("12345").as_posix() == "products/123/45/12345"


def test_exporter_writes_confirmed_product_json(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=True)

    result = exporter.export_confirmed_product(
        "627985000070",
        ConfirmedProductRequest(
            name="Manual Product",
            brand="Manual Brand",
            quantity="500 mL",
            image_url="https://example.test/product.jpg",
            notes="Typed in dashboard",
        ),
    )

    product_path = tmp_path / "products" / "627" / "985" / "627985000070" / "product.json"
    payload = json.loads(product_path.read_text())
    assert result.product_json_path == product_path
    assert payload["schema_version"] == 1
    assert payload["barcode"] == "627985000070"
    assert payload["name"] == "Manual Product"
    assert payload["brand"] == "Manual Brand"
    assert payload["quantity"] == "500 mL"
    assert payload["image_url"] == "https://example.test/product.jpg"
    assert payload["source"] == "user_confirmed"
    assert payload["confirmed_at"]


def test_disabled_exporter_does_not_write_files(tmp_path) -> None:
    exporter = CommunityCatalogExporter(path=tmp_path, enabled=False)

    result = exporter.export_confirmed_product("627985000070", ConfirmedProductRequest(name="Manual Product"))

    assert result.exported is False
    assert not (tmp_path / "products").exists()
