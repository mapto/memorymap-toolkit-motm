"""Metadati (person metadata) import logic.

Reads metadati_*.xlsx files and imports person records, relationships,
interviews, and birth places via the Django REST API.

The implementation is split by concern. ``values`` and ``sheets`` clean cells
and parse workbooks without calling the API. ``timespans``, ``people``,
``places``, ``relationships``, and ``interviews`` each handle one kind of record
in the API. ``importer`` runs them in order, one person record at a time.

The names below are re-exported here, so callers can write
``from metadati import ...``. ``metadati.ipynb`` imports ``import_all_metadati``
this way. Other packages import ``read_person_record`` from here too:
``person_taxonomy.augment``, ``person_biography.sources``,
``rebuild_locations``, and ``validate_data``. Some underscore-prefixed names are
re-exported because the tests use them.

The cache dicts are the same objects as in their submodules, so clearing one
here clears the shared cache. ``_location_workbook_cache`` is the exception: it
is copied at import time and stays None. The live cache is
``metadati.places._location_workbook_cache``.
"""

from metadati.values import (
    clean_label,
    clean_value,
    clean_metadata_value,
    _date_interval,
    _split_biographical_date_range,
    parse_coordinates,
    parse_name,
    parse_source_label,
)

from metadati.timespans import (
    _timespan_cache,
    get_or_create_timespan,
    _data_date_interval,
    _compatible_date_or_existing,
    _maybe_update_lifespan,
)

from metadati.people import (
    PERSON_METADATA_FIELDS,
    _person_cache,
    get_or_create_person,
)

from metadati.interviews import (
    create_interview,
)

from metadati.relationships import (
    RELATIONSHIP_MAP,
    _relationship_type_cache,
    _relationship_cache,
    get_or_create_relationship_type,
    _is_unnamed_relative,
    _merge_unnamed_relatives,
    create_relationship,
)

# Snapshot only: the live cache is metadati.places._location_workbook_cache.
from metadati.places import (
    _location_workbook_cache,
    get_or_create_region_hierarchy,
    get_or_create_location,
    _maybe_update_person_place,
)

from metadati.sheets import (
    _read_sheet_rows,
    _parse_identifier,
    _update_birth_place,
    _parse_person_field,
    _new_interview,
    _parse_source_field,
    _parse_person_sheet,
    _parse_family_sheet,
    read_person_record,
)

from metadati.importer import (
    import_record,
    import_from_xlsx,
    import_all_metadati,
)

__all__ = [
    "clean_label",
    "clean_value",
    "clean_metadata_value",
    "_date_interval",
    "_split_biographical_date_range",
    "parse_coordinates",
    "parse_name",
    "parse_source_label",
    "_timespan_cache",
    "get_or_create_timespan",
    "_data_date_interval",
    "_compatible_date_or_existing",
    "_maybe_update_lifespan",
    "PERSON_METADATA_FIELDS",
    "_person_cache",
    "get_or_create_person",
    "create_interview",
    "RELATIONSHIP_MAP",
    "_relationship_type_cache",
    "_relationship_cache",
    "get_or_create_relationship_type",
    "_is_unnamed_relative",
    "_merge_unnamed_relatives",
    "create_relationship",
    "_location_workbook_cache",
    "get_or_create_region_hierarchy",
    "get_or_create_location",
    "_maybe_update_person_place",
    "_read_sheet_rows",
    "_parse_identifier",
    "_update_birth_place",
    "_parse_person_field",
    "_new_interview",
    "_parse_source_field",
    "_parse_person_sheet",
    "_parse_family_sheet",
    "read_person_record",
    "import_record",
    "import_from_xlsx",
    "import_all_metadati",
]
