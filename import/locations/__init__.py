"""Expose the location reference API used by the import pipeline.

Production code imports from this package rather than from its submodules.
The submodules are split by responsibility: ``synonyms`` holds the reviewed
location-to-GO rules, ``names`` normalizes spellings, ``geo`` resolves
coordinates from GeoNames, Wikidata, and a local geocoder, ``enrich`` computes
bag-of-words and super-region values, ``db`` loads and saves ``locations.xlsx``,
and ``entities`` finds or creates API location points and their GO concepts.

Underscore-prefixed names are re-exported for the tests, which inspect
``_locations_db`` and ``_location_cache`` directly.

Usage::

    from locations import get_or_create_location, load_locations_db

    database = load_locations_db(enrich_coordinates=False)
    point_id = get_or_create_location("Gießen", locations_db=database)
"""

from locations.synonyms import (
    LOCATION_TAXONOMY_SYNONYMS_PATH,
    taxonomy_label_key,
    LocationTaxonomySynonyms,
    location_taxonomy_synonyms,
    taxonomy_alias,
    taxonomy_match_excluded,
    taxonomy_reviewed_unmapped,
    taxonomy_location_parent,
    taxonomy_query_override,
)

from locations.names import (
    normalize_location,
    canonical_location_name,
)

from locations.geo import (
    GEONAMES_USERNAME,
    domains,
    GEOCODER_URL,
    _coordinate_pair,
    extract_geonames_id,
    resolve_location_coordinates,
    extract_geonames_coordinates,
    extract_wikidata_coordinates,
    query_geocoder,
)

from locations.enrich import (
    tokenize_location,
    compute_super_regions,
    enrich_locations_xlsx,
)

from locations.db import (
    LOCATIONS_WORKBOOK_PATH,
    _locations_db,
    load_locations_db,
    _extra_url_mapping,
    save_locations_db,
    upsert_location_db,
    rebuild_location_workbook,
    link_locations_to_regions,
)

from locations.entities import (
    _location_cache,
    _prepare_location_metadata,
    _find_location_match,
    _find_concept_location,
    _reconcile_concept_owner,
    _existing_location_updates,
    _new_location_payload,
    get_or_create_location,
    sync_location_concepts,
    seed_location_entities,
    _resolve_exact_location,
)

__all__ = [
    "LOCATION_TAXONOMY_SYNONYMS_PATH",
    "taxonomy_label_key",
    "LocationTaxonomySynonyms",
    "location_taxonomy_synonyms",
    "taxonomy_alias",
    "taxonomy_match_excluded",
    "taxonomy_reviewed_unmapped",
    "taxonomy_location_parent",
    "taxonomy_query_override",
    "normalize_location",
    "canonical_location_name",
    "GEONAMES_USERNAME",
    "domains",
    "GEOCODER_URL",
    "_coordinate_pair",
    "extract_geonames_id",
    "resolve_location_coordinates",
    "extract_geonames_coordinates",
    "extract_wikidata_coordinates",
    "query_geocoder",
    "tokenize_location",
    "compute_super_regions",
    "enrich_locations_xlsx",
    "LOCATIONS_WORKBOOK_PATH",
    "_locations_db",
    "load_locations_db",
    "_extra_url_mapping",
    "save_locations_db",
    "upsert_location_db",
    "rebuild_location_workbook",
    "link_locations_to_regions",
    "_location_cache",
    "_prepare_location_metadata",
    "_find_location_match",
    "_find_concept_location",
    "_reconcile_concept_owner",
    "_existing_location_updates",
    "_new_location_payload",
    "get_or_create_location",
    "sync_location_concepts",
    "seed_location_entities",
    "_resolve_exact_location",
]
