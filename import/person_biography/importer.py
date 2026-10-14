"""Choosing dates and writing planned biographies to the API."""

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
    """Create/update Person biography fields from a validated source plan."""
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
