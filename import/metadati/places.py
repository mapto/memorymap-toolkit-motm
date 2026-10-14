"""Region hierarchy and birth-place locations for persons.

A metadati birth place comes as a name and the regions that contain it, for
example a country and then a state. This module stores the regions as
LocationRegion rows, each nested in the one before, and links the innermost
region to the location. Each region is looked up by name first, so a region
shared by several places is created once. The location itself is resolved by
``locations.get_or_create_location`` against the locations workbook, which
reuses the existing record and its coordinates.

``importer.import_record`` calls ``get_or_create_location`` for the birth place,
then ``_maybe_update_person_place`` to attach it to the Person. This module
writes only to the API.
"""

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
    """Create or reuse a LocationRegion chain and return the innermost region ID.

    ``region_list`` runs from the outermost region to the innermost. Each name is
    looked up by exact name and created when missing, with ``part_of`` set to the
    region before it. An existing region has its parent PATCHed when the parent
    differs. Empty names are skipped. Returns None for an empty list or when every
    name is empty. Side effects: API GET, POST, and PATCH calls on regions.
    """
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
    """Return the LocationPoint ID for a birth-place dict, linking its regions.

    ``bp`` is the ``birth_place`` dict from ``sheets``, with ``name``,
    ``wikidata_id``, and ``regions``. Returns None when the name is empty or the
    location cannot be resolved. The first call with a name loads the locations
    workbook without coordinate enrichment and keeps it in
    ``_location_workbook_cache``. The innermost region from
    ``get_or_create_region_hierarchy`` is then PATCHed onto the location, if there
    is one. Side effects: API calls, and one read of locations.xlsx.
    """
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
    """Set a Person's place field, or refuse to replace it with a conflicting one.

    ``importer.import_record`` uses this for the birth place. An empty field is
    PATCHed to ``location_id``. A field that already holds the same location, or a
    different location whose name ``person_biography.place_names_equivalent``
    judges equivalent to ``source_name``, is left unchanged. Any other existing
    value raises ``ValueError`` and nothing is written. Side effects: API GET of
    the Person and of the existing location, and a PATCH when the field was empty.
    """
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
