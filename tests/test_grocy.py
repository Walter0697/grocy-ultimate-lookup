import asyncio

import pytest
import httpx

from app.grocy import GrocyClient, GrocyError
from app.grocy_units import COMMON_GROCY_UNITS, missing_unit_names
from app.models import PendingProductConfirmation, ScanEventRequest


class RecordingGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "POST" and path == "/objects/products":
            return {"created_object_id": 4}
        if method == "PUT" and path == "/objects/products/4":
            return None
        if method == "GET":
            if path == "/objects/quantity_unit_conversions":
                return []
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class AddPurchaseUnitGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "GET" and path == "/objects/products/4":
            return {
                "id": 4,
                "name": "Tissue Pouch",
                "location_id": 4,
                "qu_id_purchase": 12,
                "qu_id_stock": 2,
                "qu_id_consume": 2,
                "qu_id_price": 12,
            }
        if method == "GET" and path == "/objects/quantity_unit_conversions":
            return [
                {"id": 31, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 12},
                {"id": 32, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1 / 12},
            ]
        if method == "GET":
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class UpdateRecordingGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path in {
            "/objects/products/4",
            "/objects/product_barcodes/9",
            "/objects/quantity_unit_conversions/31",
            "/objects/quantity_unit_conversions/32",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Pouch",
                    "description": None,
                    "location_id": 4,
                    "qu_id_purchase": 2,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 2,
                }
            if path == "/objects/product_barcodes":
                return [{"id": 9, "product_id": 4, "barcode": "123", "qu_id": 2}]
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 31, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 1},
                    {"id": 32, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class UpdateImageDownloadFailGrocyClient(UpdateRecordingGrocyClient):
    async def _upload_product_picture(self, barcode: str, image_url):
        raise httpx.ConnectError("All connection attempts failed")


class UpdateWithStaleRowsGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path in {
            "/objects/products/4",
            "/objects/product_barcodes/9",
            "/objects/quantity_unit_conversions/41",
            "/objects/quantity_unit_conversions/42",
        }:
            return None
        if method == "DELETE" and path in {
            "/objects/quantity_unit_conversions/43",
            "/objects/quantity_unit_conversions/44",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Pouch",
                    "description": None,
                    "location_id": 4,
                    "qu_id_purchase": 6,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 6,
                }
            if path == "/objects/product_barcodes":
                return [{"id": 9, "product_id": 4, "barcode": "123", "qu_id": 2}]
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 41, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 1},
                    {"id": 42, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1},
                    {"id": 43, "product_id": 4, "from_qu_id": 6, "to_qu_id": 2, "factor": 6},
                    {"id": 44, "product_id": 4, "from_qu_id": 2, "to_qu_id": 6, "factor": 1 / 6},
                    {"id": 45, "product_id": 4, "from_qu_id": 6, "to_qu_id": 24, "factor": 4},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class UpdateMissingBarcodeGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path == "/objects/products/4":
            return None
        if method == "POST" and path == "/objects/product_barcodes":
            return {"created_object_id": 15}
        if method == "PUT" and path in {
            "/objects/quantity_unit_conversions/51",
            "/objects/quantity_unit_conversions/52",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Pouch",
                    "description": None,
                    "location_id": 4,
                    "qu_id_purchase": 12,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 12,
                }
            if path == "/objects/product_barcodes":
                return []
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 51, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 1},
                    {"id": 52, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class CreateFailureAfterProductGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "POST" and path == "/objects/products":
            return {"created_object_id": 4}
        if method == "POST" and path == "/objects/product_barcodes":
            return {"created_object_id": 9}
        if method == "GET" and path == "/objects/quantity_unit_conversions":
            return []
        if method == "POST" and path == "/objects/quantity_unit_conversions":
            raise GrocyError("Grocy 500: conversion write failed")
        if method == "DELETE" and path == "/objects/products/4":
            return None
        raise AssertionError(f"Unexpected request: {method} {path}")


class UpdateFailureAfterProductPutGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []
        self.barcode_update_attempts = 0

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path == "/objects/products/4":
            return None
        if method == "PUT" and path == "/objects/product_barcodes/9":
            self.barcode_update_attempts += 1
            if self.barcode_update_attempts == 1:
                raise GrocyError("Grocy 500: barcode update failed")
            return None
        if method == "PUT" and path in {
            "/objects/quantity_unit_conversions/61",
            "/objects/quantity_unit_conversions/62",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Pouch",
                    "description": "Old description",
                    "location_id": 3,
                    "qu_id_purchase": 2,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 2,
                }
            if path == "/objects/product_barcodes":
                return [{"id": 9, "product_id": 4, "barcode": "123", "qu_id": 2}]
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 61, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 1},
                    {"id": 62, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        raise AssertionError(f"Unexpected request: {method} {path}")


class UpdateToSameUnitGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path in {
            "/objects/products/4",
            "/objects/product_barcodes/9",
            "/objects/quantity_unit_conversions/71",
        }:
            return None
        if method == "DELETE" and path in {
            "/objects/quantity_unit_conversions/72",
            "/objects/quantity_unit_conversions/73",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Box",
                    "description": None,
                    "location_id": 4,
                    "qu_id_purchase": 12,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 12,
                }
            if path == "/objects/product_barcodes":
                return [{"id": 9, "product_id": 4, "barcode": "123", "qu_id": 12}]
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 71, "product_id": 4, "from_qu_id": 7, "to_qu_id": 7, "factor": 1},
                    {"id": 72, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 12},
                    {"id": 73, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1 / 12},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


class UpdateToSameUnitWithoutBarcodeGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "PUT" and path in {
            "/objects/products/4",
            "/objects/quantity_unit_conversions/81",
        }:
            return None
        if method == "POST" and path == "/objects/product_barcodes":
            return {"created_object_id": 19}
        if method == "DELETE" and path in {
            "/objects/quantity_unit_conversions/82",
            "/objects/quantity_unit_conversions/83",
        }:
            return None
        if method == "GET":
            if path == "/objects/products/4":
                return {
                    "id": 4,
                    "name": "Old Tissue Box",
                    "description": None,
                    "location_id": 4,
                    "qu_id_purchase": 12,
                    "qu_id_stock": 2,
                    "qu_id_consume": 2,
                    "qu_id_price": 12,
                }
            if path == "/objects/product_barcodes":
                return []
            if path == "/objects/quantity_unit_conversions":
                return [
                    {"id": 81, "product_id": 4, "from_qu_id": 7, "to_qu_id": 7, "factor": 9},
                    {"id": 82, "product_id": 4, "from_qu_id": 12, "to_qu_id": 2, "factor": 12},
                    {"id": 83, "product_id": 4, "from_qu_id": 2, "to_qu_id": 12, "factor": 1 / 12},
                ]
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


def run(coro):
    return asyncio.run(coro)


def event(mode: str) -> ScanEventRequest:
    return ScanEventRequest(
        event_id="event-1",
        device_id="kitchen-pi",
        barcode="123",
        mode=mode,
        quantity=2,
        location_id=9,
    )


def test_product_card_includes_edit_prefill_fields() -> None:
    client = RecordingGrocyClient()

    card = client.product_card(
        {
            "product": {
                "id": 4,
                "name": "Tissue Pouch",
                "description": "Fixed details",
                "location_id": 4,
                "qu_id_purchase": 12,
                "qu_id_stock": 2,
            },
            "stock_amount": 2,
            "quantity_unit_stock": {"name": "Piece"},
            "location": {"name": "Kitchen"},
            "product_barcodes": [{"barcode": "123456"}],
        }
    )

    assert card["description"] == "Fixed details"
    assert card["location_id"] == 4
    assert card["qu_id_purchase"] == 12
    assert card["qu_id_stock"] == 2


def test_stock_operations_forward_location() -> None:
    add_client = AddPurchaseUnitGrocyClient()
    run(add_client.apply_stock_operation(4, event("add")))
    add_request = next(request for request in add_client.requests if request[0] == "POST")
    assert add_request[2]["json"]["location_id"] == 9
    assert add_request[1] == "/stock/products/4/add"

    for mode in ("remove", "set"):
        client = RecordingGrocyClient()
        run(client.apply_stock_operation(4, event(mode)))

        method, path, kwargs = client.requests[0]
        payload = client.requests[0][2]["json"]
        assert payload["location_id"] == 9
        if mode == "remove":
            assert path == "/stock/products/4/consume"
        else:
            assert path == "/stock/products/4/inventory"


def test_picture_file_name_is_unique_per_upload() -> None:
    first = GrocyClient.picture_file_name("066200032500", "https://example.com/image.jpg")
    second = GrocyClient.picture_file_name("066200032500", "https://example.com/image.jpg")

    assert first.startswith("066200032500-")
    assert first.endswith(".jpg")
    assert second.startswith("066200032500-")
    assert second.endswith(".jpg")
    assert first != second


def test_product_payload_uses_purchase_and_stock_units_with_conversion() -> None:
    payload = GrocyClient.product_payload(
        PendingProductConfirmation(
            name="Tissue Box",
            location_id=4,
            qu_id_stock=7,
            qu_id_purchase=8,
            qu_factor_purchase_to_stock=12,
        )
    )

    assert payload["qu_id_stock"] == 7
    assert payload["qu_id_consume"] == 7
    assert payload["qu_id_purchase"] == 8
    assert payload["qu_id_price"] == 8
    assert "qu_factor_purchase_to_stock" not in payload


def test_missing_unit_names_uses_case_insensitive_trimmed_match() -> None:
    existing = [{"name": " Box "}, {"name": "piece"}]

    missing = missing_unit_names(existing, ["box", "bag", "piece"])

    assert COMMON_GROCY_UNITS
    assert missing == ["bag"]


def test_create_quantity_unit_posts_name() -> None:
    client = RecordingGrocyClient()

    run(client.create_quantity_unit("bag"))

    method, path, kwargs = client.requests[0]
    assert method == "POST"
    assert path == "/objects/quantity_units"
    assert kwargs["json"] == {"name": "bag"}


def test_create_product_creates_product_specific_quantity_unit_conversions() -> None:
    client = RecordingGrocyClient()

    run(
        client.create_product(
            "123",
            PendingProductConfirmation(
                name="Tissue Pouch",
                location_id=4,
                qu_id_stock=2,
                qu_id_purchase=12,
                qu_factor_purchase_to_stock=12,
            ),
        )
    )

    conversion_requests = [
        request
        for request in client.requests
        if request[0] == "POST" and request[1] == "/objects/quantity_unit_conversions"
    ]

    assert len(conversion_requests) == 2
    assert conversion_requests[0][2]["json"] == {
        "from_qu_id": 12,
        "to_qu_id": 2,
        "factor": 12,
        "product_id": 4,
    }
    assert conversion_requests[1][2]["json"] == {
        "from_qu_id": 2,
        "to_qu_id": 12,
        "factor": 1 / 12,
        "product_id": 4,
    }


def test_update_product_rewrites_barcode_mapping_and_upserts_conversion_rows() -> None:
    client = UpdateRecordingGrocyClient()

    run(
        client.update_product(
            4,
            "123",
            PendingProductConfirmation(
                name="Tissue Pouch",
                location_id=4,
                qu_id_stock=2,
                qu_id_purchase=12,
                qu_factor_purchase_to_stock=12,
            ),
        )
    )

    barcode_updates = [
        request for request in client.requests if request[0] == "PUT" and request[1] == "/objects/product_barcodes/9"
    ]
    conversion_updates = [
        request
        for request in client.requests
        if request[0] == "PUT" and request[1].startswith("/objects/quantity_unit_conversions/")
    ]

    assert len(barcode_updates) == 1
    assert barcode_updates[0][2]["json"] == {"product_id": 4, "barcode": "123", "qu_id": 12}
    assert len(conversion_updates) == 2
    assert conversion_updates[0][2]["json"] == {
        "from_qu_id": 12,
        "to_qu_id": 2,
        "factor": 12,
        "product_id": 4,
    }
    assert conversion_updates[1][2]["json"] == {
        "from_qu_id": 2,
        "to_qu_id": 12,
        "factor": 1 / 12,
        "product_id": 4,
    }


def test_update_product_wraps_image_download_failures_as_grocy_errors() -> None:
    client = UpdateImageDownloadFailGrocyClient()

    with pytest.raises(GrocyError, match="Product image download failed"):
        run(
            client.update_product(
                4,
                "123",
                PendingProductConfirmation(
                    name="Tissue Pouch",
                    image_url="https://example.com/image.jpg",
                    location_id=4,
                    qu_id_stock=2,
                    qu_id_purchase=12,
                    qu_factor_purchase_to_stock=12,
                ),
            )
        )


def test_create_product_same_unit_only_writes_one_self_conversion() -> None:
    client = RecordingGrocyClient()

    run(
        client.create_product(
            "123",
            PendingProductConfirmation(
                name="Tissue Box",
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    conversion_requests = [
        request
        for request in client.requests
        if request[0] == "POST" and request[1] == "/objects/quantity_unit_conversions"
    ]

    assert len(conversion_requests) == 1
    assert conversion_requests[0][2]["json"] == {
        "from_qu_id": 7,
        "to_qu_id": 7,
        "factor": 1,
        "product_id": 4,
    }


def test_update_product_removes_stale_conversion_rows_after_unit_change() -> None:
    client = UpdateWithStaleRowsGrocyClient()

    run(
        client.update_product(
            4,
            "123",
            PendingProductConfirmation(
                name="Tissue Pouch",
                location_id=4,
                qu_id_stock=2,
                qu_id_purchase=12,
                qu_factor_purchase_to_stock=12,
            ),
        )
    )

    deleted_conversions = [
        request
        for request in client.requests
        if request[0] == "DELETE" and request[1].startswith("/objects/quantity_unit_conversions/")
    ]

    assert deleted_conversions == [
        ("DELETE", "/objects/quantity_unit_conversions/43", {}),
        ("DELETE", "/objects/quantity_unit_conversions/44", {}),
    ]
    assert ("DELETE", "/objects/quantity_unit_conversions/45", {}) not in deleted_conversions


def test_update_product_recreates_missing_barcode_mapping() -> None:
    client = UpdateMissingBarcodeGrocyClient()

    run(
        client.update_product(
            4,
            "123",
            PendingProductConfirmation(
                name="Tissue Pouch",
                location_id=4,
                qu_id_stock=2,
                qu_id_purchase=12,
                qu_factor_purchase_to_stock=12,
            ),
        )
    )

    barcode_creates = [
        request for request in client.requests if request[0] == "POST" and request[1] == "/objects/product_barcodes"
    ]

    assert len(barcode_creates) == 1
    assert barcode_creates[0][2]["json"] == {"product_id": 4, "barcode": "123", "qu_id": 12}


def test_create_product_raises_and_best_effort_deletes_created_product_on_later_failure() -> None:
    client = CreateFailureAfterProductGrocyClient()

    with pytest.raises(GrocyError, match="conversion write failed"):
        run(
            client.create_product(
                "123",
                PendingProductConfirmation(
                    name="Tissue Pouch",
                    location_id=4,
                    qu_id_stock=2,
                    qu_id_purchase=12,
                    qu_factor_purchase_to_stock=12,
                ),
            )
        )

    assert ("DELETE", "/objects/products/4", {}) in client.requests


def test_update_product_raises_and_best_effort_restores_barcode_and_conversions_on_later_failure() -> None:
    client = UpdateFailureAfterProductPutGrocyClient()

    with pytest.raises(GrocyError, match="barcode update failed"):
        run(
            client.update_product(
                4,
                "123",
                PendingProductConfirmation(
                    name="Tissue Pouch",
                    location_id=4,
                    qu_id_stock=2,
                    qu_id_purchase=12,
                    qu_factor_purchase_to_stock=12,
                ),
            )
        )

    restore_calls = [
        request
        for request in client.requests
        if request[0] == "PUT" and request[1] in {"/objects/quantity_unit_conversions/61", "/objects/quantity_unit_conversions/62"}
    ]
    barcode_calls = [
        request for request in client.requests if request[0] == "PUT" and request[1] == "/objects/product_barcodes/9"
    ]

    assert barcode_calls == [
        ("PUT", "/objects/product_barcodes/9", {"json": {"product_id": 4, "barcode": "123", "qu_id": 12}}),
        ("PUT", "/objects/product_barcodes/9", {"json": {"product_id": 4, "barcode": "123", "qu_id": 2}}),
    ]
    assert ("PUT", "/objects/products/4", {"json": {"name": "Old Tissue Pouch", "description": "Old description", "location_id": 3, "qu_id_purchase": 2, "qu_id_stock": 2, "qu_id_consume": 2, "qu_id_price": 2}}) in client.requests
    assert restore_calls == [
        (
            "PUT",
            "/objects/quantity_unit_conversions/61",
            {"json": {"from_qu_id": 12, "to_qu_id": 2, "factor": 1, "product_id": 4}},
        ),
        (
            "PUT",
            "/objects/quantity_unit_conversions/62",
            {"json": {"from_qu_id": 2, "to_qu_id": 12, "factor": 1, "product_id": 4}},
        ),
    ]


def test_update_product_to_same_unit_removes_stale_old_reciprocal_rows() -> None:
    client = UpdateToSameUnitGrocyClient()

    run(
        client.update_product(
            4,
            "123",
            PendingProductConfirmation(
                name="Tissue Box",
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    deleted_conversions = [
        request
        for request in client.requests
        if request[0] == "DELETE" and request[1].startswith("/objects/quantity_unit_conversions/")
    ]

    assert deleted_conversions == [
        ("DELETE", "/objects/quantity_unit_conversions/72", {}),
        ("DELETE", "/objects/quantity_unit_conversions/73", {}),
    ]


def test_update_product_to_same_unit_without_previous_barcode_row_removes_stale_old_reciprocal_rows() -> None:
    client = UpdateToSameUnitWithoutBarcodeGrocyClient()

    run(
        client.update_product(
            4,
            "123",
            PendingProductConfirmation(
                name="Tissue Box",
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    deleted_conversions = [
        request
        for request in client.requests
        if request[0] == "DELETE" and request[1].startswith("/objects/quantity_unit_conversions/")
    ]

    assert deleted_conversions == [
        ("DELETE", "/objects/quantity_unit_conversions/82", {}),
        ("DELETE", "/objects/quantity_unit_conversions/83", {}),
    ]


def test_create_product_same_unit_normalizes_self_conversion_factor_to_one() -> None:
    client = RecordingGrocyClient()

    run(
        client.create_product(
            "123",
            PendingProductConfirmation(
                name="Tissue Box",
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=9,
            ),
        )
    )

    conversion_requests = [
        request
        for request in client.requests
        if request[0] == "POST" and request[1] == "/objects/quantity_unit_conversions"
    ]

    assert len(conversion_requests) == 1
    assert conversion_requests[0][2]["json"] == {
        "from_qu_id": 7,
        "to_qu_id": 7,
        "factor": 1,
        "product_id": 4,
    }


def test_add_stock_operation_uses_purchase_barcode_unit() -> None:
    client = AddPurchaseUnitGrocyClient()

    run(client.apply_stock_operation(4, event("add")))

    method, path, kwargs = next(request for request in client.requests if request[0] == "POST")
    assert method == "POST"
    assert path == "/stock/products/4/add"
    payload = kwargs["json"]
    assert payload["amount"] == 24
    assert payload["transaction_type"] == "purchase"
    assert "barcode" not in payload


def test_remove_stock_operation_uses_stock_unit() -> None:
    client = RecordingGrocyClient()

    run(client.apply_stock_operation(4, event("remove")))

    payload = client.requests[0][2]["json"]
    assert payload["amount"] == 2
    assert payload["transaction_type"] == "consume"
    assert "barcode" not in payload


def test_set_stock_operation_uses_stock_unit() -> None:
    client = RecordingGrocyClient()

    run(client.apply_stock_operation(4, event("set")))

    payload = client.requests[0][2]["json"]
    assert payload["new_amount"] == 2
    assert "barcode" not in payload
