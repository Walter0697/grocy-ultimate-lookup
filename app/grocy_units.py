COMMON_GROCY_UNITS = [
    "piece",
    "box",
    "bag",
    "bottle",
    "can",
    "jar",
    "pack",
    "roll",
    "carton",
    "tube",
    "pouch",
    "tray",
]


def normalize_unit_name(name: str) -> str:
    return name.strip().casefold()


def missing_unit_names(existing_units: list[dict], seed_units: list[str]) -> list[str]:
    existing_names = {
        normalize_unit_name(str(unit.get("name") or ""))
        for unit in existing_units
        if unit.get("name")
    }
    return [name for name in seed_units if normalize_unit_name(name) not in existing_names]
