"""Checking existing API records against planned biographies."""

from __future__ import annotations

from typing import Mapping
from api_client import api_get
from person_taxonomy import load_person_taxonomy_synonyms
from person_biography.model import PersonBiographyConflictError
from person_biography.identity import _people_by_identity
from person_biography.spans import _span_intersection, _span_label, _stored_date_span
from person_biography.places import place_names_equivalent, _location_name
from person_biography.plan import _plan_values


def _as_object_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return [value]
    return []


def validate_existing_person_biographies(plan) -> None:
    """Read-only API preflight for existing Person biography conflicts."""
    biographies = _plan_values(plan)
    if not biographies:
        return
    aliases = load_person_taxonomy_synonyms().aliases
    people = _as_object_list(api_get("persons"))
    people_by_identity = _people_by_identity(people, aliases)
    timespans = {
        str(item.get("id")): item
        for item in _as_object_list(api_get("timespans"))
        if item.get("id") is not None
    }
    location_cache: dict[str, str | None] = {}
    conflicts = []

    for biography in biographies:
        matches = people_by_identity.get(biography.identity_key, [])
        for person in matches:
            timespan_id = person.get("lifespan")
            if timespan_id:
                timespan = timespans.get(str(timespan_id))
                if timespan is None:
                    timespan = api_get(f"timespans/{timespan_id}")
                if isinstance(timespan, Mapping):
                    for kind in ("birth", "death"):
                        incoming = getattr(biography, f"{kind}_span")
                        existing_value = timespan.get(
                            "start" if kind == "birth" else "end"
                        )
                        metadata_span = getattr(biography, f"metadata_{kind}_span")
                        existing_span = _stored_date_span(
                            existing_value,
                            metadata_span,
                        )
                        if (
                            incoming
                            and existing_span
                            and _span_intersection(incoming, existing_span) is None
                        ):
                            conflicts.append(
                                f"Existing Person {person['id']} {kind} date "
                                f"{_span_label(existing_span)} conflicts with "
                                f"planned value {_span_label(incoming)} for "
                                f"{biography.person_name!r}"
                            )

            for kind in ("birth", "death"):
                incoming_place = getattr(biography, f"{kind}_place")
                existing_id = person.get(f"{kind}_place")
                if not incoming_place or not existing_id:
                    continue
                existing_place = _location_name(existing_id, location_cache)
                if existing_place and not place_names_equivalent(
                    incoming_place, existing_place
                ):
                    conflicts.append(
                        f"Existing Person {person['id']} {kind} place "
                        f"{existing_place!r} conflicts with planned value "
                        f"{incoming_place!r} for {biography.person_name!r}"
                    )

    if conflicts:
        raise PersonBiographyConflictError(conflicts)
