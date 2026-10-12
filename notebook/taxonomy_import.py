"""Persist a parsed :class:`taxonomy.Taxonomy` in the Memory Map API.

This module owns the side-effectful import boundary. It consumes the
side-effect-free hierarchy produced by :mod:`taxonomy`, creates concepts
parent-first, records the API IDs for taxonomy paths, and resolves source
labels used by people, locations, time periods, and events. Keeping this
separate from :mod:`taxonomy` means parsing and validation can run without
network access, while API matching and persistence remain explicit and easy
to mock in importer tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import re

from locations import (
    taxonomy_alias,
    taxonomy_label_key,
    taxonomy_location_parent,
    taxonomy_match_excluded,
)
from taxonomy import Taxonomy, TaxonomyError, TaxonomyNode, _extract_key, _label_key


ConceptCreator = Callable[..., int | None]


@dataclass
class TaxonomyImport:
    """ID mapping produced after one taxonomy has been persisted.

    The object is deliberately separate from :class:`taxonomy.Taxonomy`:
    the latter describes source structure, while this class describes the
    corresponding remote records and provides resolvers for import clients.
    """

    taxonomy: Taxonomy
    ids_by_key: dict[tuple[str, ...], int]
    nodes_by_key: dict[tuple[str, ...], TaxonomyNode]
    aliases: dict[str, tuple[str, ...]]
    create_concept: ConceptCreator

    def resolve_concept(self, label: str, top_level: str | None = None) -> int | None:
        """Resolve a source label to its taxonomy concept ID.

        A top-level selector is required when the source label is intentionally
        repeated across categories. Unknown event vocabulary is ignored so an
        import cannot create unparented concepts outside the taxonomy.
        """
        key = _label_key(label)
        if not key:
            return None
        alias_key = self.aliases.get(key) if top_level is None else None
        if alias_key is not None:
            return self.ids_by_key[alias_key]

        candidates = [
            node
            for node in self.nodes_by_key.values()
            if _label_key(node.label) == key
            and (
                top_level is None
                or _label_key(_extract_key(node.top_level)) == _label_key(top_level)
            )
        ]
        if not candidates:
            return None
        if len(candidates) > 1:
            paths = [" > ".join(node.key) for node in candidates]
            raise TaxonomyError(
                f"Source label {label!r} is ambiguous in the taxonomy: {paths}"
            )
        return self.ids_by_key[candidates[0].key]

    def resolve_location(
        self,
        label: str,
        *,
        allow_aliases: bool = True,
        allow_embedded: bool = True,
    ) -> int | None:
        """Resolve a source location to its most specific GO concept.

        Metadata and chronotopi use descriptive variants such as street
        addresses or ``KZ Buchenwald``. Exact labels and reviewed synonyms are
        tried first; otherwise the longest canonical GO label embedded in the
        source name is used. Reviewed exclusions, including Koblenz, remain
        deliberately unmapped.
        """
        if taxonomy_match_excluded(label):
            return None
        direct = self.resolve_concept(label, "GO")
        if direct is not None:
            return direct

        canonical = taxonomy_alias(label)
        if allow_aliases and canonical != label:
            direct = self.resolve_concept(canonical, "GO")
            if direct is not None:
                return direct

        if not allow_embedded:
            return None

        normalized = taxonomy_label_key(canonical)
        candidates = []
        for node in self.nodes_by_key.values():
            if _label_key(_extract_key(node.top_level)) != "go":
                continue
            node_label = taxonomy_label_key(node.label)
            if node_label and re.search(
                rf"(?:^| ){re.escape(node_label)}(?: |$)", normalized
            ):
                candidates.append((len(node_label), node))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return self.ids_by_key[candidates[0][1].key]

    def resolve_time_period(self, label: str) -> int | None:
        """Resolve a time-period label under the Zeitangaben category."""
        return self.resolve_concept(label, "Zeitangaben")

    def resolve_location_exact(self, label: str) -> int | None:
        """Resolve only an exact or reviewed-alias GO location label.

        Address and descriptive variants must not claim the unique concept ID
        of their containing city; the locations taxonomy handles that visual
        containment separately.
        """
        return self.resolve_location(
            label,
            allow_aliases=True,
            allow_embedded=False,
        )

    def ensure_location_concept(self, label: str) -> int | None:
        """Resolve or create one canonical supplemental GO location concept."""
        if taxonomy_match_excluded(label):
            return None
        resolved = self.resolve_location_exact(label)
        if resolved is not None:
            return resolved

        canonical = taxonomy_alias(label)
        key = _label_key(canonical)
        parent_label = taxonomy_location_parent(canonical)
        parent_id = self.resolve_concept(parent_label, "GO") if parent_label else None
        if parent_id is None:
            parent_id = self.resolve_concept("GO – geographischer Ort", "GO")
        if parent_id is None:
            raise TaxonomyError(f"No GO parent available for location {canonical!r}")

        identity = ("go", "supplemental", key)
        for node in self.nodes_by_key.values():
            if node.key == identity:
                return self.ids_by_key[node.key]
        concept_id = self.create_concept(
            canonical,
            parent_id=parent_id,
            identity=identity,
        )
        if concept_id is None:
            raise TaxonomyError(f"Could not create supplemental location {canonical!r}")
        node = TaxonomyNode(
            key=identity,
            label=canonical,
            parent_key=("go", _label_key(parent_label or "GO – geographischer Ort")),
            top_level="GO – geographischer Ort",
        )
        self.nodes_by_key[identity] = node
        self.ids_by_key[identity] = concept_id
        return concept_id

    def resolve_person(self, label: str) -> int | None:
        """Resolve a person taxonomy label under the Personae category."""
        return self.resolve_concept(label, "Personae")


def import_taxonomy(taxonomy: Taxonomy, create_concept: ConceptCreator) -> TaxonomyImport:
    """Persist taxonomy nodes parent-first and return their resolved IDs.

    ``taxonomy`` supplies validated structure only. ``create_concept`` is the
    injected API adapter, which keeps this module independent of HTTP details
    and lets tests verify ordering, parent IDs, and duplicate-label behavior
    without a live server.
    """
    nodes = taxonomy.concept_nodes()
    ids_by_key: dict[tuple[str, ...], int] = {}
    nodes_by_key = {node.key: node for node in nodes}

    for node in nodes:
        parent_id = ids_by_key.get(node.parent_key) if node.parent_key else None
        concept_id = create_concept(
            node.label,
            parent_id=parent_id,
            icon=node.icon or None,
            identity=node.key,
        )
        if concept_id is None:
            raise TaxonomyError(f"Could not import taxonomy node {node.label!r}")
        ids_by_key[node.key] = concept_id

    return TaxonomyImport(
        taxonomy=taxonomy,
        ids_by_key=ids_by_key,
        nodes_by_key=nodes_by_key,
        aliases=taxonomy.import_aliases(),
        create_concept=create_concept,
    )
