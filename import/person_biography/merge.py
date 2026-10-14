"""Combining source facts into one biography per person."""

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
