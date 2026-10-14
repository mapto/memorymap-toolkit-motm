"""Combining source facts into one biography per person.

Each chronotopi sheet's facts are first combined with its metadati values by
``_combine_source_facts``. When a second sheet or workbook resolves to a person
already in the plan, ``_merge_biographies`` folds it in. Both use the same
rules. Overlapping spans are intersected, equivalent places keep the existing
spelling, and any disagreement is appended to a shared conflict list. The plan
raises that list as one ``PersonBiographyConflictError`` after the sources have
been read, so one run reports the disagreements together. Neither function
touches the API. Both change their first argument in place.
"""

from __future__ import annotations

from typing import Any, Mapping
from person_biography.model import _MutableBiography
from person_biography.spans import _span_intersection, _span_label, _merge_span
from person_biography.places import place_names_equivalent, _merge_place


def _combine_source_facts(
    event_facts: _MutableBiography,
    metadata: Mapping[str, Any] | None,
    metadata_name: str,
    conflicts: list[str],
) -> _MutableBiography:
    """Add one metadati record's birth and death values to a sheet's facts.

    An overlapping chronotopi span is replaced by its overlap with the metadati
    span. A span that does not overlap, or a place that is not equivalent, is
    appended to ``conflicts``. A metadati span or place fills an empty chronotopi
    field. The metadati values are also copied to the ``metadata_*`` fields, which
    the apply step uses to tell a year-level start from an exact day. When
    ``metadata`` is None, ``event_facts`` is returned unchanged. The argument is
    changed in place and returned. Without this step, a sheet would be planned
    from chronotopi alone, and a disagreement with its metadati workbook would go
    unnoticed.
    """
    if metadata is None:
        return event_facts

    metadata_context = f"metadata workbook {metadata_name!r}"
    for kind in ("birth", "death"):
        event_span = getattr(event_facts, f"{kind}_span")
        metadata_span = metadata.get(f"{kind}_span")
        if event_span and metadata_span:
            intersection = _span_intersection(event_span, metadata_span)
            if intersection is None:
                conflicts.append(
                    f"{event_facts.person_name!r} {kind} date: chronotopi "
                    f"{_span_label(event_span)} conflicts with "
                    f"{_span_label(metadata_span)} in {metadata_context}"
                )
            else:
                setattr(event_facts, f"{kind}_span", intersection)
        elif metadata_span:
            setattr(event_facts, f"{kind}_span", metadata_span)

        event_place = getattr(event_facts, f"{kind}_place")
        metadata_place = metadata.get(f"{kind}_place")
        if (
            event_place
            and metadata_place
            and not place_names_equivalent(event_place, metadata_place)
        ):
            conflicts.append(
                f"{event_facts.person_name!r} {kind} place: chronotopi "
                f"{event_place!r} conflicts with {metadata_place!r} in "
                f"{metadata_context}"
            )
        elif metadata_place and not event_place:
            setattr(event_facts, f"{kind}_place", metadata_place)

        setattr(event_facts, f"metadata_{kind}_span", metadata_span)
        setattr(event_facts, f"metadata_{kind}_place", metadata_place)
    return event_facts


def _merge_biographies(
    existing: _MutableBiography,
    incoming: _MutableBiography,
    conflicts: list[str],
) -> None:
    """Fold a second source's facts for one person into ``existing``, in place.

    Called by ``build_person_biography_plan`` when a sheet or workbook resolves to
    an identity key already in the plan. The plan holds one entry per key, so the
    second set of facts must be merged rather than stored beside the first. Birth
    and death spans and places, and their ``metadata_*`` counterparts, follow the
    rules in ``_combine_source_facts``. Source labels are unioned, and conflicts
    are appended to ``conflicts``.
    """
    for kind in ("birth", "death"):
        for suffix in ("span", "place"):
            attribute = f"{kind}_{suffix}"
            if suffix == "span":
                merged = _merge_span(
                    getattr(existing, attribute),
                    getattr(incoming, attribute),
                    description=(
                        f"{existing.person_name!r} {kind} facts across "
                        f"{', '.join(sorted(existing.source_workbooks | incoming.source_workbooks))}"
                    ),
                    conflicts=conflicts,
                )
            else:
                merged = _merge_place(
                    getattr(existing, attribute),
                    getattr(incoming, attribute),
                    description=f"{existing.person_name!r} {kind} places across sources",
                    conflicts=conflicts,
                )
            setattr(existing, attribute, merged)

            metadata_attribute = f"metadata_{attribute}"
            if suffix == "span":
                metadata_value = _merge_span(
                    getattr(existing, metadata_attribute),
                    getattr(incoming, metadata_attribute),
                    description=f"Metadata {kind} dates for {existing.person_name!r}",
                    conflicts=conflicts,
                )
            else:
                metadata_value = _merge_place(
                    getattr(existing, metadata_attribute),
                    getattr(incoming, metadata_attribute),
                    description=f"Metadata {kind} places for {existing.person_name!r}",
                    conflicts=conflicts,
                )
            setattr(existing, metadata_attribute, metadata_value)
    existing.source_workbooks.update(incoming.source_workbooks)
