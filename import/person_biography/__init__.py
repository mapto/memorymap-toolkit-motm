"""Extract, validate, and import birth/death facts from chronotopi sources."""

from person_biography.model import (
    PersonBiographyError,
    PersonBiographyConflictError,
    PersonBiography,
    _MutableBiography,
)

from person_biography.identity import (
    _clean_name,
    _alias_target,
    _identity_from_name,
    _identity_from_person_fields,
    _api_identity,
    _people_by_identity,
)

from person_biography.spans import (
    _parse_span,
    _span_from_interval,
    _record_span,
    _span_intersection,
    _span_label,
    _event_date_span,
    _merge_span,
    _stored_date_span,
)

from person_biography.places import (
    _clean_place,
    _normalized_place,
    _place_match_keys,
    place_names_equivalent,
    _merge_place,
    _location_name,
)

from person_biography.sources import (
    _BIRTH_WORDS,
    _DEATH_WORDS,
    _OTHER_SUBJECT_RE,
    _classify_biographical_event,
    _metadata_people,
    _collect_sheet_facts,
    _rows_for_sheet,
    _basename,
    _metadata_for_workbook,
)

from person_biography.merge import (
    _combine_source_facts,
    _merge_biographies,
)

from person_biography.plan import (
    build_person_biography_plan,
    _plan_values,
)

from person_biography.validate import (
    _as_object_list,
    validate_existing_person_biographies,
)

from person_biography.importer import (
    _choose_date,
    import_person_biographies,
)

__all__ = [
    "PersonBiographyError",
    "PersonBiographyConflictError",
    "PersonBiography",
    "_MutableBiography",
    "_clean_name",
    "_alias_target",
    "_identity_from_name",
    "_identity_from_person_fields",
    "_api_identity",
    "_people_by_identity",
    "_parse_span",
    "_span_from_interval",
    "_record_span",
    "_span_intersection",
    "_span_label",
    "_event_date_span",
    "_merge_span",
    "_stored_date_span",
    "_clean_place",
    "_normalized_place",
    "_place_match_keys",
    "place_names_equivalent",
    "_merge_place",
    "_location_name",
    "_BIRTH_WORDS",
    "_DEATH_WORDS",
    "_OTHER_SUBJECT_RE",
    "_classify_biographical_event",
    "_metadata_people",
    "_collect_sheet_facts",
    "_rows_for_sheet",
    "_basename",
    "_metadata_for_workbook",
    "_combine_source_facts",
    "_merge_biographies",
    "build_person_biography_plan",
    "_plan_values",
    "_as_object_list",
    "validate_existing_person_biographies",
    "_choose_date",
    "import_person_biographies",
]
