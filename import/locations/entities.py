"""Location entity creation, matching, and concept seeding."""

import logging
from typing import Any
from locations.synonyms import taxonomy_match_excluded
from locations.names import normalize_location, canonical_location_name
from locations.geo import (
    _coordinate_pair,
    extract_geonames_id,
    resolve_location_coordinates,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Location API operations (get-or-create, region linking)
# ---------------------------------------------------------------------------

_location_cache = {}


def _prepare_location_metadata(
    name,
    wikidata_qid=None,
    geonames_id=None,
    *,
    locations_db=None,
    normalize_fn=None,
):
    """Normalize source values and resolve cached/source location metadata."""
    name = str(name).strip()
    key = (normalize_fn or normalize_location)(name)
    db_entry = dict((locations_db or {}).get(key, {}))
    db_entry.setdefault("name", name)
    if wikidata_qid and not db_entry.get("wikidata_url"):
        db_entry["wikidata_url"] = f"https://www.wikidata.org/wiki/{wikidata_qid}"
    if geonames_id and not db_entry.get("geonames_url"):
        db_entry["geonames_url"] = f"https://www.geonames.org/{geonames_id}"

    coordinates = _coordinate_pair(db_entry)
    if coordinates is None:
        coordinates = resolve_location_coordinates(db_entry)
    return {
        "name": name,
        "key": key,
        "coordinates": coordinates,
        "wikidata_id": db_entry.get("wikidata_id")
        or (wikidata_qid if wikidata_qid and wikidata_qid not in ("", "nan") else None),
        "geonames_id": (
            extract_geonames_id(db_entry.get("geonames_id"))
            or extract_geonames_id(db_entry.get("geonames_url"))
            or extract_geonames_id(geonames_id)
        ),
    }


def _find_location_match(existing, key, normalize_fn):
    """Find an existing API location with the same normalized name."""
    return next(
        (
            location
            for location in existing
            if normalize_fn(location["current_name"]) == key
        ),
        None,
    )


def _find_concept_location(api_get, concept_id, exclude_id=None):
    """Find the location already owning a unique taxonomy concept, if any."""
    if not concept_id:
        return None
    return next(
        (
            location
            for location in api_get("locations")
            if location.get("concept") == concept_id
            and location.get("id") != exclude_id
        ),
        None,
    )


def _reconcile_concept_owner(api_get, api_patch, match, linked, concept_id, key, norm):
    """Keep the exact canonical name as the owner of a unique concept."""
    if linked is None:
        return match
    if match is not None and norm(match["current_name"]) == key:
        if linked["id"] != match["id"]:
            api_patch("locations", linked["id"], {"concept": None})
        api_patch("locations", match["id"], {"concept": concept_id})
        return match
    return linked


def _existing_location_updates(metadata, match, concept_id):
    """Build only missing metadata updates for an existing API location."""
    updates = {}
    if metadata["coordinates"] is not None and not match.get("location"):
        updates["latitude"], updates["longitude"] = metadata["coordinates"]
    if metadata["wikidata_id"] and not match.get("wikidata_id"):
        updates["wikidata_id"] = metadata["wikidata_id"]
    if metadata["geonames_id"] and not match.get("geonames_id"):
        updates["geonames_id"] = metadata["geonames_id"]
    if concept_id and not match.get("concept"):
        updates["concept"] = concept_id
    return updates


def _new_location_payload(metadata, concept_id):
    """Build the API payload for a new location point."""
    payload: dict[str, Any] = {"current_name": metadata["name"]}
    if metadata["coordinates"] is not None:
        payload["latitude"], payload["longitude"] = metadata["coordinates"]
    if metadata["wikidata_id"]:
        payload["wikidata_id"] = metadata["wikidata_id"]
    if metadata["geonames_id"]:
        payload["geonames_id"] = metadata["geonames_id"]
    if concept_id:
        payload["concept"] = concept_id
    return payload


def get_or_create_location(
    name,
    wikidata_qid=None,
    geonames_id=None,
    *,
    locations_db=None,
    normalize_fn=None,
    concept_id=None,
):
    """Create or retrieve a LocationPoint through focused import helpers."""
    from api_client import api_get, api_patch, api_post

    if not name or str(name).strip() in ("", "nan"):
        return None
    canonical_name = canonical_location_name(name, locations_db)
    if canonical_name is None:
        return None
    name = canonical_name
    norm = normalize_fn or normalize_location
    metadata = _prepare_location_metadata(
        name,
        wikidata_qid,
        geonames_id,
        locations_db=locations_db,
        normalize_fn=normalize_fn,
    )
    key = metadata["key"] if normalize_fn is None else norm(metadata["name"])
    if key in _location_cache:
        cached_id = _location_cache[key]
        if not concept_id:
            return cached_id
        try:
            cached = api_get(f"locations/{cached_id}")
        except Exception:
            cached = None
        if cached and cached.get("concept") == concept_id:
            return cached_id
        linked = _find_concept_location(api_get, concept_id, cached_id)
        if linked:
            owner = _reconcile_concept_owner(
                api_get,
                api_patch,
                cached,
                linked,
                concept_id,
                key,
                norm,
            )
            _location_cache[key] = owner["id"]
            return owner["id"]
        if cached and not cached.get("concept"):
            api_patch("locations", cached_id, {"concept": concept_id})
        return cached_id
    try:
        existing = api_get("locations", params={"search": metadata["name"]})
    except Exception:
        logger.exception("Location API lookup failed for %s", metadata["name"])
        return None
    match = _find_location_match(existing, key, norm)
    linked = None
    if concept_id and (match is None or not match.get("concept")):
        linked = _find_concept_location(
            api_get,
            concept_id,
            match["id"] if match else None,
        )
    if linked:
        owner = _reconcile_concept_owner(
            api_get,
            api_patch,
            match,
            linked,
            concept_id,
            key,
            norm,
        )
        _location_cache[key] = owner["id"]
        return owner["id"]
    if match:
        updates = _existing_location_updates(metadata, match, concept_id)
        if updates:
            try:
                api_patch("locations", match["id"], updates)
            except Exception:
                logger.exception(
                    "Location API update failed for %s (id=%s)",
                    metadata["name"],
                    match["id"],
                )
        _location_cache[key] = match["id"]
        return match["id"]
    payload = _new_location_payload(metadata, concept_id)
    try:
        created = api_post("locations", payload, fail_on_error=False)
    except Exception:
        logger.exception("Location API create failed for %s", metadata["name"])
        return None
    if created is None:
        logger.error(
            "Skipping location %r because the API rejected it", metadata["name"]
        )
        return None
    _location_cache[key] = created["id"]
    return created["id"]


def sync_location_concepts(resolve_location, *, api_get=None, api_patch=None):
    """Attach every resolvable imported location point to its GO concept.

    This runs after taxonomy creation so metadata points created earlier and
    chronotopi points created later share the same canonical concept IDs.
    Existing concepts are preserved; reviewed exclusions are left untouched.
    """
    if api_get is None or api_patch is None:
        from api_client import api_get as default_get, api_patch as default_patch

        api_get = api_get or default_get
        api_patch = api_patch or default_patch

    matched = []
    unmapped = []
    locations = api_get("locations")
    concept_owners = {
        location["concept"]: location["id"]
        for location in locations
        if location.get("concept")
    }
    for location in locations:
        if location.get("concept"):
            continue
        concept_id = _resolve_exact_location(
            resolve_location, location.get("current_name", "")
        )
        if concept_id is None:
            unmapped.append(location.get("current_name", ""))
            continue
        if concept_id in concept_owners:
            unmapped.append(location.get("current_name", ""))
            continue
        api_patch("locations", location["id"], {"concept": concept_id})
        concept_owners[concept_id] = location["id"]
        matched.append((location["id"], concept_id))
    return {"matched": matched, "unmapped": unmapped}


def seed_location_entities(locations_db, resolve_location=None):
    """Ensure every rebuilt workbook row has one imported API entity.

    Metadata points are created before chronotopi runs, so this step reuses
    exact metadata names, creates missing canonical workbook entities, and
    attaches the shared GO concept whenever the taxonomy resolves the name.
    """
    from api_client import api_get, api_patch

    resolved_entries = []
    for _, entry in sorted(locations_db.items()):
        name = entry.get("name")
        if not name:
            continue
        concept_id = (
            _resolve_exact_location(resolve_location, name)
            if resolve_location
            else None
        )
        if (
            resolve_location
            and concept_id is None
            and not taxonomy_match_excluded(name)
        ):
            raise RuntimeError(f"Canonical location {name!r} has no GO concept mapping")
        resolved_entries.append((name, entry, concept_id))

    created_or_reused = []
    concept_owners = {
        location["concept"]: location["id"]
        for location in api_get("locations")
        if location.get("concept")
    }
    for name, entry, concept_id in resolved_entries:
        location_id = get_or_create_location(
            name,
            wikidata_qid=entry.get("wikidata_id"),
            geonames_id=entry.get("geonames_id"),
            locations_db=locations_db,
            concept_id=concept_id,
        )
        if location_id is not None:
            if concept_id:
                owner_id = concept_owners.get(concept_id)
                if owner_id and owner_id != location_id:
                    api_patch("locations", owner_id, {"concept": None})
                api_patch("locations", location_id, {"concept": concept_id})
                concept_owners[concept_id] = location_id
                refreshed = api_get(f"locations/{location_id}")
                if refreshed.get("concept") != concept_id:
                    raise RuntimeError(
                        f"Location {name!r} did not retain concept {concept_id}"
                    )
            created_or_reused.append((name, location_id, concept_id))
    return created_or_reused


def _resolve_exact_location(resolve_location, name):
    """Resolve a canonical label with aliases enabled but embedded matching off."""
    try:
        return resolve_location(
            name,
            allow_aliases=True,
            allow_embedded=False,
        )
    except TypeError:
        # Supplemental-concept resolvers expose a one-argument interface and
        # apply the same exact-or-alias rule internally.
        return resolve_location(name)
