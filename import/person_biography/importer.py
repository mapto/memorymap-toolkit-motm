"""Choosing dates and writing planned biographies to the API.

This is the apply step. The notebook calls it after
``build_person_biography_plan`` and ``validate_existing_person_biographies``, and
after the taxonomy concepts and locations exist, so place lookups can link to
them. Nothing in this module checks that order. It is the only step of the
biography import that writes. For each planned biography it finds the Person,
compares the stored lifespan and places with the plan, and writes what changed:

- ``get_or_create_timespan`` creates a timespan when a planned date differs from
  the stored one, and the Person's ``lifespan`` is pointed at it.
- ``get_or_create_location`` finds or creates a birth or death place when the
  Person has none. It may also query external coordinate services.
- ``api_patch`` updates the Person once, with all changed fields.

``get_person_id`` runs first for each biography and also writes. It creates a
Person when no record matches, and it can merge duplicate Person records.
Dates and places are reconciled here rather than in the plan, because the stored
values are only known after the API lookup. Stored places are never replaced. A
stored date is kept unless it is blank or a metadata-derived start that the plan
narrows. Writes made before a conflict is raised are not rolled back, which is
why the validate step runs first.
"""

from __future__ import annotations

from typing import Any, Mapping
from api_client import api_get, api_patch, get_or_create_timespan, get_person_id
from locations import get_or_create_location
from timespan import Timespan
from utils import clean_str
from person_biography.model import PersonBiographyError, PersonBiographyConflictError
from person_biography.spans import _span_intersection, _span_label, _stored_date_span
from person_biography.places import place_names_equivalent, _location_name
from person_biography.plan import _plan_values


def _choose_date(
    current_value: Any,
    incoming_span: Timespan | None,
    metadata_span: Timespan | None,
    *,
    person_name: str,
    kind: str,
) -> str | None:
    """Return the date to keep or store for one Person birth or death field.

    Args:
        current_value: The date stored on the Person, or None.
        incoming_span: The planned span, or None when the plan has no date.
        metadata_span: The metadati span for the same field. It tells a
            year-level start from an exact day.
        person_name: Used in conflict messages.
        kind: ``"birth"`` or ``"death"``, used in conflict messages.

    Returns:
        The ISO date to keep or store. The planned start replaces the stored
        value only when the stored value is blank, or when it is the metadata
        start and the plan narrows it. In every other case that does not raise,
        the stored value is kept, and None means neither side has a date.

    Raises:
        PersonBiographyConflictError: The stored date cannot be parsed or does
            not overlap the planned span.
    """
    current = clean_str(current_value) or None
    if incoming_span is None or incoming_span.start is None:
        return current
    incoming_value = incoming_span.start.isoformat()
    if not current:
        return incoming_value
    if current == incoming_value:
        return current

    existing_span = _stored_date_span(current, metadata_span)
    if existing_span and _span_intersection(existing_span, incoming_span):
        if (
            metadata_span
            and metadata_span.start
            and metadata_span.end
            and current == metadata_span.start.isoformat()
            and (
                incoming_span.start > metadata_span.start
                or (incoming_span.end or incoming_span.start) < metadata_span.end
            )
        ):
            return incoming_value
        return current

    raise PersonBiographyConflictError(
        [
            f"Existing Person {kind} date {current!r} conflicts with planned "
            f"value {_span_label(incoming_span)} for {person_name!r}"
        ]
    )


def import_person_biographies(
    plan,
    *,
    locations_db=None,
    location_concept_resolver=None,
) -> list[int]:
    """Write each planned biography to its Person and return the Person IDs.

    This is the apply step, and it writes to the API. For each biography,
    ``get_person_id`` finds or creates the Person. The Person and its lifespan
    are then read. This function sends at most one PATCH per Person, through
    ``api_patch``, and only when a value changed. Timespan and location records
    are created by ``get_or_create_timespan`` and ``get_or_create_location`` when
    a change needs them.

    Args:
        plan: The dict from ``build_person_biography_plan``, or any iterable of
            ``PersonBiography`` values.
        locations_db: Reviewed location table, keyed by normalized name. It
            supplies coordinates and identifiers to ``get_or_create_location``.
        location_concept_resolver: Optional callable that maps a place name to a
            GO concept ID, or to None.

    Returns:
        One Person ID per biography processed, in plan order, whether or not
        anything changed. A biography is skipped only when ``get_person_id``
        returns no ID, which happens only for a blank name.

    Raises:
        PersonBiographyError: A Person cannot be read back after lookup.
        PersonBiographyConflictError: A planned date or place clashes with the
            stored value. HTTP errors from the API client are not caught here.
    """
    imported = []
    location_cache: dict[str, str | None] = {}
    for biography in _plan_values(plan):
        person_id = get_person_id(biography.person_name, biography.person_name)
        if not person_id:
            continue
        person = api_get(f"persons/{person_id}")
        if not isinstance(person, Mapping):
            raise PersonBiographyError(
                f"Could not refresh Person {person_id} for {biography.person_name!r}"
            )

        current_timespan = {}
        timespan_id = person.get("lifespan")
        if timespan_id:
            result = api_get(f"timespans/{timespan_id}")
            if isinstance(result, Mapping):
                current_timespan = result

        birth_value = _choose_date(
            current_timespan.get("start"),
            biography.birth_span,
            biography.metadata_birth_span,
            person_name=biography.person_name,
            kind="birth",
        )
        death_value = _choose_date(
            current_timespan.get("end"),
            biography.death_span,
            biography.metadata_death_span,
            person_name=biography.person_name,
            kind="death",
        )
        patch = {}
        if birth_value or death_value:
            if birth_value != clean_str(
                current_timespan.get("start")
            ) or death_value != clean_str(current_timespan.get("end")):
                new_timespan_id = get_or_create_timespan(
                    start=birth_value,
                    end=death_value,
                )
                if new_timespan_id and new_timespan_id != timespan_id:
                    patch["lifespan"] = new_timespan_id

        for kind in ("birth", "death"):
            place = getattr(biography, f"{kind}_place")
            if not place:
                continue
            field_name = f"{kind}_place"
            current_id = person.get(field_name)
            if current_id:
                current_name = _location_name(current_id, location_cache)
                if current_name and not place_names_equivalent(place, current_name):
                    raise PersonBiographyConflictError(
                        [
                            f"Existing Person {kind} place {current_name!r} "
                            f"conflicts with planned value {place!r} for "
                            f"{biography.person_name!r}"
                        ]
                    )
                continue

            concept_id = (
                location_concept_resolver(place) if location_concept_resolver else None
            )
            location_id = get_or_create_location(
                place,
                locations_db=locations_db,
                concept_id=concept_id,
            )
            if location_id:
                patch[field_name] = location_id

        if patch:
            api_patch("persons", person_id, patch)
        imported.append(person_id)
    return imported
