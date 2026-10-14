"""Occurrence and hierarchy helpers for the Personae branch.

``augment_personae_taxonomy`` edits the Personae branch as a list of
``TaxonomyOccurrence`` records. The list is needed because the label-keyed
``hierarchy`` dictionary cannot tell repeated labels apart, and augmentation
moves people between branches, which changes parent links. The helpers here
read that list, reorder it so every parent precedes its children, rebuild the
``hierarchy`` dictionary for the merged ``Taxonomy``, and identify Personae
nodes. They also flag collective family nodes, which name a family rather than
a person.

The helpers are internal to the package. They do not call the API or touch the
filesystem. Malformed parent links, cycles, and unreachable nodes raise
``PersonTaxonomyError``, so a bad tree is reported before the importer runs.
"""

from __future__ import annotations

from typing import Sequence
from taxonomy import ROOT_KEY, Taxonomy, TaxonomyOccurrence, _extract_key, _label_key
from person_taxonomy.keys import person_taxonomy_key
from person_taxonomy.model import PersonTaxonomyError


def _occurrences_for(taxonomy: Taxonomy) -> list[TaxonomyOccurrence]:
    """Return a new list of the taxonomy's occurrences.

    A taxonomy loaded from a Mermaid file already carries occurrences, which keep
    repeated labels apart. A taxonomy built only from a label hierarchy has none,
    so they are rebuilt from ``concept_nodes()``, which yields parents first. The
    list is always new, so augmentation can append to it without changing the
    caller's taxonomy. Raises ``PersonTaxonomyError`` if a node's parent is
    missing from the rebuild.
    """
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
    """Rebuild the label-keyed hierarchy that ``Taxonomy`` expects.

    The result maps ``ROOT_KEY`` to the top-level labels and every label to its
    child labels, with an empty list for a leaf. It is recomputed after
    augmentation edits the occurrences, so the merged taxonomy's ``hierarchy``
    agrees with its occurrences. Repeated labels share one entry, so uniqueness
    is checked separately by ``Taxonomy.validate_unique_labels``.
    """
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
    """Reindex occurrences so each parent precedes its children.

    Augmentation can move an existing person under a family branch that was
    appended later in the list, which breaks parent-first order. The
    ``concept_nodes`` walk needs each parent's index to be smaller than its
    children's, so this walks the tree from the roots and rewrites
    ``parent_index``, ``top_level``, and ``path`` for the new order. It raises
    ``PersonTaxonomyError`` for an invalid parent index, a cycle, or a node that
    cannot be reached from a root.
    """
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
        """Append one occurrence, then recurse into its children.

        Reaching a node that is still on the current walk means a cycle. Reaching
        a node that was already placed means it has two paths. Either case raises
        ``PersonTaxonomyError``.
        """
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
