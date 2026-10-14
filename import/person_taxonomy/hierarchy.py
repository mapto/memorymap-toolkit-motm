"""Occurrence and hierarchy helpers for the Personae branch."""

from __future__ import annotations

from typing import Sequence
from taxonomy import ROOT_KEY, Taxonomy, TaxonomyOccurrence, _extract_key, _label_key
from person_taxonomy.keys import person_taxonomy_key
from person_taxonomy.model import PersonTaxonomyError


def _occurrences_for(taxonomy: Taxonomy) -> list[TaxonomyOccurrence]:
    if taxonomy.occurrences:
        return list(taxonomy.occurrences)

    occurrences = []
    indexes_by_key = {}
    for node in taxonomy.concept_nodes():
        parent_index = indexes_by_key.get(node.parent_key)
        if node.parent_key is not None and parent_index is None:
            raise PersonTaxonomyError(
                f"Could not reconstruct the parent for taxonomy node {node.label!r}"
            )
        path = (
            (node.label,)
            if parent_index is None
            else occurrences[parent_index].path + (node.label,)
        )
        occurrences.append(
            TaxonomyOccurrence(
                label=node.label,
                parent_index=parent_index,
                top_level=node.top_level,
                path=path,
            )
        )
        indexes_by_key[node.key] = len(occurrences) - 1
    return occurrences


def _hierarchy_from_occurrences(
    occurrences: Sequence[TaxonomyOccurrence],
) -> dict[str, list[str]]:
    hierarchy: dict[str, list[str]] = {ROOT_KEY: []}
    for occurrence in occurrences:
        if occurrence.parent_index is None:
            hierarchy[ROOT_KEY].append(occurrence.label)
        else:
            parent = occurrences[occurrence.parent_index]
            hierarchy.setdefault(parent.label, []).append(occurrence.label)
        hierarchy.setdefault(occurrence.label, [])
    return hierarchy


def _parent_first_occurrences(
    occurrences: Sequence[TaxonomyOccurrence],
) -> list[TaxonomyOccurrence]:
    """Reindex occurrences so each parent precedes its children."""
    children: dict[int, list[int]] = {}
    roots = []
    for index, occurrence in enumerate(occurrences):
        if occurrence.parent_index is None:
            roots.append(index)
            continue
        if not 0 <= occurrence.parent_index < len(occurrences):
            raise PersonTaxonomyError(
                f"Taxonomy node {occurrence.label!r} has an invalid parent index"
            )
        children.setdefault(occurrence.parent_index, []).append(index)

    ordered: list[TaxonomyOccurrence] = []
    new_indexes: dict[int, int] = {}
    visiting: set[int] = set()

    def visit(index: int) -> None:
        if index in visiting:
            raise PersonTaxonomyError("Personae taxonomy contains a parent cycle")
        if index in new_indexes:
            raise PersonTaxonomyError(
                f"Taxonomy occurrence {occurrences[index].label!r} has multiple paths"
            )
        visiting.add(index)
        occurrence = occurrences[index]
        if occurrence.parent_index is None:
            parent_index = None
            top_level = occurrence.top_level
            path = (occurrence.label,)
        else:
            parent_index = new_indexes.get(occurrence.parent_index)
            if parent_index is None:
                raise PersonTaxonomyError(
                    f"Could not reindex parent for taxonomy node {occurrence.label!r}"
                )
            parent = ordered[parent_index]
            top_level = parent.top_level
            path = parent.path + (occurrence.label,)
        new_indexes[index] = len(ordered)
        ordered.append(
            TaxonomyOccurrence(
                label=occurrence.label,
                parent_index=parent_index,
                top_level=top_level,
                path=path,
            )
        )
        for child_index in children.get(index, []):
            visit(child_index)
        visiting.remove(index)

    for root_index in roots:
        visit(root_index)
    if len(ordered) != len(occurrences):
        raise PersonTaxonomyError(
            "Personae taxonomy contains an unreachable occurrence or parent cycle"
        )
    return ordered


def _is_personae_occurrence(occurrence: TaxonomyOccurrence) -> bool:
    return _label_key(_extract_key(occurrence.top_level)) == _label_key("Personae")


def _is_collective_label(label: str) -> bool:
    return person_taxonomy_key(label).endswith((" familie", " family"))
