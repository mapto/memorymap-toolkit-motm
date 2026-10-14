"""Region hierarchy and birth-place locations for persons."""

from __future__ import annotations

from api_client import api_get, api_patch, api_post
from utils import is_empty
from locations import (
    get_or_create_location as get_or_create_location_point,
    load_locations_db,
)

_location_workbook_cache = None


# ---------------------------------------------------------------------------
# Location (birth place)
# ---------------------------------------------------------------------------


def get_or_create_region_hierarchy(region_list):
    """Create or retrieve a chain of LocationRegion objects via the API.
    Returns the innermost region's id, or None."""
    if not region_list:
        return None

    parent_id = None
    for name in region_list:
        if is_empty(name):
            continue

        existing = api_get("regions", params={"search": name})
        match = next((r for r in existing if r["name"] == name), None)

        if match:
            region_id = match["id"]
            if parent_id and match.get("part_of") != parent_id:
                api_patch("regions", region_id, {"part_of": parent_id})
        else:
            payload = {"name": name}
            if parent_id:
                payload["part_of"] = parent_id
            created = api_post("regions", payload)
            region_id = created["id"]

        parent_id = region_id

    return parent_id


def get_or_create_location(bp):
    """Create or retrieve a LocationPoint from a birth_place dict."""
    if is_empty(bp.get("name")):
        return None
    global _location_workbook_cache
    if _location_workbook_cache is None:
        _location_workbook_cache = load_locations_db(enrich_coordinates=False)
    loc_id = get_or_create_location_point(
        bp["name"],
        wikidata_qid=bp.get("wikidata_id"),
        locations_db=_location_workbook_cache,
    )
    if loc_id is None:
        return None
    region_id = get_or_create_region_hierarchy(bp.get("regions"))
    if region_id:
        api_patch("locations", loc_id, {"region": region_id})
    return loc_id


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------


def _maybe_update_person_place(person_id, field_name, location_id, source_name):
    person = api_get(f"persons/{person_id}")
    existing_id = person.get(field_name) if isinstance(person, dict) else None
    if existing_id:
        if str(existing_id) == str(location_id):
            return
        existing_location = api_get(f"locations/{existing_id}")
        existing_name = (
            existing_location.get("current_name") or existing_location.get("name")
            if isinstance(existing_location, dict)
            else None
        )
        from person_biography import place_names_equivalent

        if existing_name and place_names_equivalent(source_name, existing_name):
            return
        raise ValueError(
            f"Refusing to overwrite Person {person_id} {field_name} "
            f"{existing_name!r} with conflicting metadata value {source_name!r}"
        )
    api_patch("persons", person_id, {field_name: location_id})
