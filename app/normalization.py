import re


SIZE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s?(fl\s?oz|fluid\s?ounce|oz|ml|mL|l|L|g|kg|lb|lbs|ct|count|loads?)\b",
    re.IGNORECASE,
)
CASE_PATTERN = re.compile(r"\bcase\s+of\s+(\d+)\b", re.IGNORECASE)
MULTIPACK_PATTERN = re.compile(r"\b(\d+)\s?[- ]?(pack|pk|count|ct)\b", re.IGNORECASE)
LOAD_COUNT_PATTERN = re.compile(r"\b(\d+)\s?loads?\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")


class NormalizedProduct:
    def __init__(
        self,
        *,
        normalized_name: str,
        brand: str | None,
        size: str | None,
        count: int | None,
        variant: str | None,
    ) -> None:
        self.normalized_name = normalized_name
        self.brand = brand
        self.size = size
        self.count = count
        self.variant = variant


def normalize_product_name(raw_name: str, brand: str | None = None, quantity: str | None = None) -> NormalizedProduct:
    name = normalize_whitespace(raw_name)
    normalized_brand = normalize_whitespace(brand) if brand else None
    normalized_quantity = normalize_whitespace(quantity) if quantity else None

    count = extract_count(name)
    size = normalized_quantity or extract_size(name)
    name = strip_suffix_noise(name)
    name = strip_embedded_size_and_count(name)
    name = normalize_whitespace(name)

    variant = extract_variant(name)
    return NormalizedProduct(
        normalized_name=name,
        brand=normalized_brand,
        size=size,
        count=count,
        variant=variant,
    )


def normalize_whitespace(value: str | None) -> str:
    return WHITESPACE_PATTERN.sub(" ", value or "").strip()


def extract_count(value: str) -> int | None:
    case_match = CASE_PATTERN.search(value)
    if case_match:
        return int(case_match.group(1))

    pack_match = MULTIPACK_PATTERN.search(value)
    if pack_match:
        return int(pack_match.group(1))

    load_match = LOAD_COUNT_PATTERN.search(value)
    if load_match:
        return int(load_match.group(1))

    return None


def extract_size(value: str) -> str | None:
    matches = list(SIZE_PATTERN.finditer(value))
    if not matches:
        return None

    match = matches[-1]
    amount = match.group(1)
    unit = normalize_unit(match.group(2))
    return f"{amount} {unit}"


def normalize_unit(unit: str) -> str:
    normalized = unit.lower().replace(" ", "")
    unit_map = {
        "floz": "fl oz",
        "fluidounce": "fl oz",
        "loads": "loads",
        "load": "loads",
        "ml": "mL",
        "l": "L",
        "lbs": "lb",
        "count": "ct",
    }
    return unit_map.get(normalized, normalized)


def strip_suffix_noise(value: str) -> str:
    value = re.sub(r"\s+case\s+of\s+\d+\b", "", value, flags=re.IGNORECASE)
    return normalize_whitespace(value)


def strip_embedded_size_and_count(value: str) -> str:
    value = SIZE_PATTERN.sub("", value)
    value = MULTIPACK_PATTERN.sub("", value)
    value = re.sub(r"\s+-\s*$", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    return normalize_whitespace(value)


def extract_variant(value: str) -> str | None:
    if " - " not in value:
        return None

    candidate = normalize_whitespace(value.rsplit(" - ", 1)[-1])
    if not candidate:
        return None
    return candidate
