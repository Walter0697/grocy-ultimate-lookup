from app.normalization import normalize_product_name


def test_normalizes_upcitemdb_case_count_noise() -> None:
    result = normalize_product_name("Lysol 2058 Disinfecting Wipes - Citrus  Case Of 12", brand="Lysol")

    assert result.normalized_name == "Lysol 2058 Disinfecting Wipes - Citrus"
    assert result.brand == "Lysol"
    assert result.count == 12
    assert result.variant == "Citrus"


def test_extracts_size_from_verbose_laundry_name() -> None:
    result = normalize_product_name(
        "Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent 100 Loads - 144 fl oz",
        brand="Gain",
    )

    assert result.normalized_name == "Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent"
    assert result.brand == "Gain"
    assert result.size == "144 fl oz"
    assert result.count == 100


def test_prefers_quantity_field_for_size() -> None:
    result = normalize_product_name("Tomato Ketchup", brand="Heinz", quantity="750 mL")

    assert result.normalized_name == "Tomato Ketchup"
    assert result.brand == "Heinz"
    assert result.size == "750 mL"
