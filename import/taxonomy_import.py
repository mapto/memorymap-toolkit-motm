"""Persist a parsed :class:`taxonomy.Taxonomy` in the Memory Map API.

This module owns the side-effectful import boundary. It consumes the
side-effect-free hierarchy produced by :mod:`taxonomy`, creates concepts
parent-first, records the API IDs for taxonomy paths, and resolves source
labels used by people, locations, time periods, and events. Keeping this
separate from :mod:`taxonomy` means parsing and validation can run without
network access, while API matching and persistence remain explicit and easy
to mock in importer tests.

The chronotopi notebook calls :func:`import_taxonomy` once, after
``rebuild_location_workbook`` and before the location, biography, and event
imports. It passes ``get_or_create_concept`` from :mod:`api_client` as the
concept creator and then uses the returned :class:`TaxonomyImport`.
``validate_data.py`` runs the same function with a counter that hands out fake
IDs, so resolution can be checked without writes. This module makes no HTTP
calls itself; every write happens inside the injected concept creator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
import re

from locations import (
    taxonomy_alias,
    taxonomy_label_key,
    taxonomy_location_parent,
    taxonomy_match_excluded,
)
from taxonomy import Taxonomy, TaxonomyError, TaxonomyNode, _extract_key, _label_key
from person_taxonomy import person_taxonomy_key


ConceptCreator = Callable[..., int | None]


@dataclass
class TaxonomyImport:
    """Hold the ID mapping produced after one taxonomy has been persisted.

    The object is deliberately separate from :class:`taxonomy.Taxonomy`:
    the latter describes source structure, while this class describes the
    corresponding remote records and provides resolvers for import clients.

    Normally created by :func:`import_taxonomy`. ``ids_by_key`` maps each
    taxonomy path to its API concept ID, and ``nodes_by_key`` holds the
    matching nodes, including supplemental location nodes. ``aliases`` maps
    normalized source vocabulary to taxonomy paths, and ``person_aliases`` maps
    normalized person spellings to canonical Personae labels. The
    ``create_concept`` callable is kept for supplemental locations. Only
    ``ensure_location_concept`` creates concepts; the ``resolve_*`` methods
    return None for unknown labels.
    """

    taxonomy: Taxonomy
    ids_by_key: dict[tuple[str, ...], int]
    nodes_by_key: dict[tuple[str, ...], TaxonomyNode]
    aliases: dict[str, tuple[str, ...]]
    person_aliases: dict[str, str]
    create_concept: ConceptCreator

    def resolve_concept(self, label: str, top_level: str | None = None) -> int | None:
        """Resolve a source label to its taxonomy concept ID.

        Matching uses the normalized label key. With ``top_level`` set, only
        nodes under that category, such as ``"Zeitangaben"``, are considered.
        Without it, reviewed aliases are checked first, and a label that occurs
        in more than one category raises ``TaxonomyError``, so repeated labels
        need a top-level selector. An unknown label returns None and is never
        created. Event import uses this as its category resolver and drops None
        results, so no unparented concepts are created. The chronotopi notebook
        reports labels that resolve to None.
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
        deliberately unmapped. Import code calls ``resolve_location_exact``,
        which turns embedded matching off so that an address does not take the
        concept of its city.

        Args:
            label: Source location name.
            allow_aliases: Whether reviewed synonyms are tried.
            allow_embedded: Whether a GO label embedded in the name may match.

        Returns:
            The concept ID of the matched GO node, or None when the name is
            excluded or nothing matches.
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
        """Resolve a time-period label under the Zeitangaben category.

        Only nodes under ``Zeitangaben`` are considered, and reviewed aliases
        are not applied. Returns None for an unknown label. Event import passes
        each row's ``date_label`` here and attaches any ID it gets to the event.
        """
        return self.resolve_concept(label, "Zeitangaben")

    def resolve_location_exact(self, label: str) -> int | None:
        """Resolve only an exact or reviewed-alias GO location label.

        Address and descriptive variants must not claim the concept of their
        containing city, so embedded matching is off. Their containment is kept
        in the location workbook instead, in ``wider_region`` and
        ``super_region``. Returns None for any other label. The biography and
        event imports receive this method as their location resolver, and
        ``validate_data.py`` calls it directly.
        """
        return self.resolve_location(
            label,
            allow_aliases=True,
            allow_embedded=False,
        )

    def ensure_location_concept(self, label: str) -> int | None:
        """Resolve or create a supplemental GO node with its configured parent chain.

        This is the only resolver that writes. A location missing from the GO
        taxonomy gets a concept under its reviewed parent hint, and missing
        ancestors are created first. ``seed_location_entities`` raises when a
        canonical location has no GO concept, so the notebook passes this
        method to it. Returns None for reviewed exclusions. Raises
        ``TaxonomyError`` for a missing parent hint, cyclic hints, an
        unavailable parent, or a creation that returns no ID.
        """
        return self._ensure_location_concept(label, resolving=set())

    def _ensure_location_concept(
        self, label: str, *, resolving: set[str]
    ) -> int | None:
        """Create a missing location and any missing configured ancestors.

        ``resolving`` holds the keys of the parent chain being created. Meeting
        one of them again means the parent hints form a cycle, which raises
        ``TaxonomyError``. Created locations are recorded in ``ids_by_key`` under
        the identity ``("go", "supplemental", key)``, so later calls reuse them.
        """
        if taxonomy_match_excluded(label):
            return None
        resolved = self.resolve_location_exact(label)
        if resolved is not None:
            return resolved

        canonical = taxonomy_alias(label)
        key = _label_key(canonical)
        if key in resolving:
            raise TaxonomyError(
                f"Cyclic canonical parent hints while importing {canonical!r}"
            )
        identity = ("go", "supplemental", key)
        existing = self.ids_by_key.get(identity)
        if existing is not None:
            return existing

        next_resolving = {*resolving, key}
        parent_label = taxonomy_location_parent(canonical)
        if parent_label:
            parent_id = self.resolve_location_exact(parent_label)
            if parent_id is None:
                parent_id = self._ensure_location_concept(
                    parent_label,
                    resolving=next_resolving,
                )
        else:
            raise TaxonomyError(
                f"No canonical parent hint for supplemental location {canonical!r}"
            )
        if parent_id is None:
            raise TaxonomyError(f"No GO parent available for location {canonical!r}")

        concept_id = self.create_concept(
            canonical,
            parent_id=parent_id,
            identity=identity,
        )
        if concept_id is None:
            raise TaxonomyError(f"Could not create supplemental location {canonical!r}")
        parent_key = next(
            (
                candidate_key
                for candidate_key, candidate_id in self.ids_by_key.items()
                if candidate_id == parent_id
            ),
            None,
        )
        if parent_key is None:
            raise TaxonomyError(
                f"Could not identify imported GO parent for {canonical!r}"
            )
        node = TaxonomyNode(
            key=identity,
            label=canonical,
            parent_key=parent_key,
            top_level="GO – geographischer Ort",
        )
        self.nodes_by_key[identity] = node
        self.ids_by_key[identity] = concept_id
        return concept_id

    def resolve_person(self, label: str) -> int | None:
        """Resolve a source spelling to a person concept under Personae.

        The spelling is normalized with ``person_taxonomy_key`` and mapped
        through the reviewed ``person_aliases`` when one exists. Returns None
        for blank names and names that are not Personae concepts. Event import
        passes each protagonist here, and ``validate_data.py`` uses it to check
        that each person sheet resolves.
        """
        key = person_taxonomy_key(label)
        if not key:
            return None
        canonical = self.person_aliases.get(key, label)
        return self.resolve_concept(canonical, "Personae")


def import_taxonomy(
    taxonomy: Taxonomy,
    create_concept: ConceptCreator,
    *,
    person_aliases: Mapping[str, str] | None = None,
) -> TaxonomyImport:
    """Persist taxonomy nodes parent-first and return their resolved IDs.

    One concept is created for each node, parents before children, and each
    child receives its parent's ID. ``create_concept`` is the only write path.
    The chronotopi notebook passes ``get_or_create_concept``, and the dry run in
    ``validate_data.py`` passes a counter. Person aliases are checked before the
    first call, so an invalid alias creates nothing. The injected creator keeps
    this module free of HTTP details and lets tests check ordering and parent
    IDs without a server.

    Args:
        taxonomy: Parsed source taxonomy whose validated nodes are imported.
        create_concept: Called with the label, ``parent_id`` and ``identity``
            keywords, and ``icon`` for taxonomy nodes. Returns the concept ID
            or None.
        person_aliases: Source spelling to canonical Personae label, usually
            ``augment_personae_taxonomy(...).aliases``. Conflicting entries,
            unknown targets, and non-leaf targets are rejected.

    Returns:
        A :class:`TaxonomyImport` holding the ID of every node and the
        resolvers.

    Raises:
        TaxonomyError: For duplicate labels within a top-level category, invalid
            person aliases, or a ``create_concept`` call that returns None.
    """
    nodes = taxonomy.concept_nodes()
    ids_by_key: dict[tuple[str, ...], int] = {}
    nodes_by_key = {node.key: node for node in nodes}
    normalized_person_aliases: dict[str, str] = {}
    personae_nodes = [
        node
        for node in nodes
        if _label_key(_extract_key(node.top_level)) == _label_key("Personae")
    ]
    personae_labels = {_label_key(node.label) for node in personae_nodes}
    personae_parent_keys = {
        node.parent_key for node in personae_nodes if node.parent_key is not None
    }
    personae_leaf_labels = {
        _label_key(node.label)
        for node in personae_nodes
        if node.parent_key is not None and node.key not in personae_parent_keys
    }
    for source, target in (person_aliases or {}).items():
        source_key = person_taxonomy_key(source)
        target_label = target.strip()
        if not source_key or not target_label:
            continue
        previous = normalized_person_aliases.get(source_key)
        if previous and _label_key(previous) != _label_key(target_label):
            raise TaxonomyError(
                f"Conflicting person aliases for {source!r}: "
                f"{previous!r} and {target_label!r}"
            )
        if _label_key(target_label) not in personae_labels:
            raise TaxonomyError(
                f"Person alias target {target_label!r} is not in the Personae taxonomy"
            )
        if _label_key(target_label) not in personae_leaf_labels:
            raise TaxonomyError(
                f"Person alias target {target_label!r} is not a Personae leaf"
            )
        normalized_person_aliases[source_key] = target_label

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
        person_aliases=normalized_person_aliases,
        create_concept=create_concept,
    )
