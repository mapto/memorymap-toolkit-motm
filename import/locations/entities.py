"""Create, match, and link location entities and their GO concepts.

The import aims for one API LocationPoint per normalized place name, and for each
GO concept to belong to at most one point. ``get_or_create_location`` finds or
creates the point for a name. ``sync_location_concepts`` attaches concepts to
existing points that lack them, and ``seed_location_entities`` makes sure every
canonical workbook row has a point with its concept.

Callers are ``events``, ``person_biography.importer``, and ``metadati.places``,
which call ``get_or_create_location``, and the chronotopi notebook, which runs
the seed and sync steps after ``import_taxonomy``. All API access goes through
``api_client``. The process-wide ``_location_cache`` answers repeated names
without an API search; tests reset it directly.
"""

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
    """Normalize source values and resolve cached/source location metadata.

    Builds the single metadata dict that ``get_or_create_location`` uses for
    matching and for the API payload. The workbook record for the name's key is
    copied, so changes made while resolving do not reach the workbook. Missing
    Wikidata and GeoNames URLs are built from the IDs. Coordinates come from the
    record or, when it has none, from ``resolve_location_coordinates``, which may
    make network requests.

    Returns a dict with ``name``, ``key``, ``coordinates``, ``wikidata_id``, and
    ``geonames_id``.
    """
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
    """Find an existing API location with the same normalized name.

    ``existing`` is the list returned by a name search on the API. Each record's
    ``current_name`` is normalized with ``normalize_fn`` and compared with
    ``key``. Returns the first match, or None.
    """
    return next(
        (
            location
            for location in existing
            if normalize_fn(location["current_name"]) == key
        ),
        None,
    )


def _find_concept_location(api_get, concept_id, exclude_id=None):
    """Find the location already owning a unique taxonomy concept, if any.

    Fetches every location with one ``api_get("locations")`` call and returns the
    first whose ``concept`` equals ``concept_id``, skipping ``exclude_id``. Returns
    None when ``concept_id`` is falsy. The lookup keeps a GO concept from being
    attached to a second point.
    """
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
    """Keep the exact canonical name as the owner of a unique concept.

    ``linked`` is the point that already holds ``concept_id``. If ``linked`` is
    None, ``match`` is returned unchanged. If ``match`` has the canonical name (its
    normalized name equals ``key``), the concept moves to it: ``linked`` is cleared
    and ``match`` is set, using up to two PATCH calls through ``api_patch``.
    Otherwise ``linked`` keeps the concept and is returned.
    """
    if linked is None:
        return match
    if match is not None and norm(match["current_name"]) == key:
        if linked["id"] != match["id"]:
            api_patch("locations", linked["id"], {"concept": None})
        api_patch("locations", match["id"], {"concept": concept_id})
        return match
    return linked


def _existing_location_updates(metadata, match, concept_id):
    """Build only missing metadata updates for an existing API location.

    Compares the prepared metadata with the API record and returns the fields the
    record lacks: coordinates when it has no ``location`` value, then the Wikidata
    ID, the GeoNames ID, and the concept. Values already on the record are never
    overwritten. The dict is ready for ``api_patch`` and is empty when nothing is
    missing.
    """
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
    """Build the API payload for a new location point.

    ``current_name`` is always included. Coordinates, the Wikidata and GeoNames
    IDs, and the concept are included only when they have values. The dict is the
    body of the POST to the ``locations`` endpoint.
    """
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
    """Create or retrieve a LocationPoint through focused import helpers.

    Event, person-biography, and metadata places all go through this function, so
    one place name maps to one point. The name is first cleaned by
    ``canonical_location_name``, which maps it to its workbook entity when
    ``locations_db`` is given. Blank, URL, and reviewed-unmapped names return None.
    A process cache answers repeated names without an API search, but a given
    ``concept_id`` is still checked against the cached point. Otherwise the point
    is found by name or created. A matching point that already has a concept keeps
    it. When another point holds ``concept_id``, the canonical-name point takes the
    concept over; otherwise that owner is returned.

    Args:
        name: Source place name. It is mapped to its canonical workbook name first.
        wikidata_qid: Wikidata QID, stored when the point has none.
        geonames_id: GeoNames ID or URL, normalized before it is stored.
        locations_db: Workbook records keyed by ``normalize_location``, or None.
        normalize_fn: Matching-key function that replaces ``normalize_location``.
        concept_id: GO concept to attach to the point.

    Returns the point's API ID, or None when the name maps to nothing or the
    lookup or create call fails. Those failures are logged. PATCH errors from
    concept linking propagate. Coordinates missing from ``locations_db`` are
    resolved before the cache is checked, so cached names can still trigger
    network requests.
    """
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

    ``resolve_location`` maps a point's name to a concept ID, or to None. The
    chronotopi notebook passes ``TaxonomyImport.ensure_location_concept``, which
    can create a supplemental concept through the injected creator and can raise
    ``TaxonomyError``. An exception stops the loop, and points already patched stay
    patched. A point is reported as unmapped when its name resolves to nothing, or
    to a concept that another point already holds. Points that already have a
    concept are skipped. The API helpers default to ``api_client``.

    Returns ``{"matched": [(location_id, concept_id), ...], "unmapped": [...]}``.
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

    Rows are processed in key order, and rows without a name are skipped. When
    ``resolve_location`` is given, every row is resolved first. A row that
    resolves to nothing, and is not a reviewed exclusion, raises ``RuntimeError``
    before any location point is created or patched. Each row then goes through
    ``get_or_create_location``. A resolved concept is moved off any other point
    that holds it, set on the row's point, and read back to confirm it stuck. A
    mismatch raises ``RuntimeError``. Resolver exceptions propagate.

    Returns ``[(name, location_id, concept_id), ...]`` for rows that got a point.
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
    """Resolve a canonical label with aliases enabled but embedded matching off.

    Calls the resolver with ``allow_aliases=True`` and ``allow_embedded=False``.
    A resolver without those keywords, such as
    ``TaxonomyImport.ensure_location_concept``, raises ``TypeError`` and is then
    called with the label alone. That resolver applies the exact-or-alias rule
    itself, but it can also create a supplemental concept. Any ``TypeError`` from
    the first call, including one raised inside a resolver that accepts the
    keywords, triggers the one-argument retry.
    """
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
