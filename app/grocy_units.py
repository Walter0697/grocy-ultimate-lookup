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


async def seed_units(grocy_client, seed_units: list[str] | None = None) -> dict:
    seed_units = seed_units or COMMON_GROCY_UNITS
    existing_units = await grocy_client.get_objects("quantity_units")
    missing = missing_unit_names(existing_units, seed_units)
    existing_names = {
        normalize_unit_name(str(unit.get("name") or "")): str(unit.get("name") or "").strip()
        for unit in existing_units
        if unit.get("name")
    }
    already_exists = [name for name in seed_units if normalize_unit_name(name) in existing_names]
    added = []
    failed = []
    for name in missing:
        try:
            await grocy_client.create_quantity_unit(name)
            added.append(name)
        except Exception as exc:
            failed.append({"name": name, "error": str(exc)})
    return {"added": added, "already_exists": already_exists, "failed": failed}
