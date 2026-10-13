"""Merge reviewed person names and metadata into the Personae concept tree."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from taxonomy import (
    ROOT_KEY,
    Taxonomy,
    TaxonomyOccurrence,
    _extract_key,
    _label_key,
)


PERSON_TAXONOMY_SYNONYMS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "person_taxonomy_synonyms.json"
)
_NAME_PLACEHOLDERS = {"", "?", "unknown", "unbekannt", "n/a", "nan", "none"}


class PersonTaxonomyError(ValueError):
    """Raised when source person labels cannot be mapped unambiguously."""


@dataclass(frozen=True)
class PersonName:
    """A person's family and given names, as written in a 'Surname, Given' label."""

    family_name: str
    given_name: str

    @classmethod
    def from_label(cls, label: str) -> PersonName | None:
        """Parse a 'Surname, Given' label; return None when it has no comma."""
        if "," not in label:
            return None
        family_name, given_name = (part.strip() for part in label.split(",", 1))
        return cls(family_name=family_name, given_name=given_name)

    @property
    def label(self) -> str:
        """The reviewed Personae form, 'Surname, Given'."""
        return f"{self.family_name}, {self.given_name}"

    @property
    def natural_order(self) -> str:
        """The sheet and metadata form, 'Given Surname'."""
        return f"{self.given_name} {self.family_name}"

    def variants(self) -> list[str]:
        """Source spellings that refer to this person."""
        return [self.natural_order, self.label]


@dataclass(frozen=True)
class PersonTaxonomySynonyms:
    """Reviewed person aliases and metadata links from the synonyms JSON.

    The mappings are read-only; copy them before changing anything.
    """

    aliases: Mapping[str, str]
    metadata_by_chronotopi: Mapping[str, str]
    metadata_relatives: Mapping[str, Mapping[str, PersonName]]

    def canonical_label(self, value: str) -> str | None:
        """Return the reviewed canonical Personae label for a source name."""
        key = person_taxonomy_key(value)
        target = self.aliases.get(key)
        if target:
            return target
        for canonical in self.aliases.values():
            if key == person_taxonomy_key(canonical):
                return canonical
            name = PersonName.from_label(canonical)
            if name is not None and key == person_taxonomy_key(name.natural_order):
                return canonical
        return None

    def metadata_workbook_for(self, chronotopi_source: str | Path) -> str | None:
        """Return the metadata workbook reviewed for a chronotopi workbook."""
        return self.metadata_by_chronotopi.get(Path(str(chronotopi_source)).name)

    def metadata_relative_name(
        self, metadata_source: str | Path | None, relation: str
    ) -> PersonName | None:
        """Return the reviewed person for an unnamed relative of one workbook.

        Links are scoped to one workbook, because the same relation text can name
        different people in different families.
        """
        if not metadata_source:
            return None
        links = self.metadata_relatives.get(Path(str(metadata_source)).name, {})
        return links.get(person_taxonomy_key(relation))


def person_taxonomy_key(value: str) -> str:
    """Normalize punctuation and spacing without guessing name-token order."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


@lru_cache(maxsize=8)
def _read_person_taxonomy_synonyms(path: str) -> PersonTaxonomySynonyms:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PersonTaxonomyError("Person taxonomy synonym data must be a JSON object")

    aliases: dict[str, str] = {}
    for source, target in data.get("aliases", {}).items():
        source_key = person_taxonomy_key(source)
        target_label = _clean_name(target)
        if not source_key or not target_label:
            raise PersonTaxonomyError(
                f"Person synonym entries need non-empty source and target: {source!r}"
            )
        previous = aliases.get(source_key)
        if previous and person_taxonomy_key(previous) != person_taxonomy_key(
            target_label
        ):
            raise PersonTaxonomyError(
                f"Conflicting person aliases for {source!r}: {previous!r} and "
                f"{target_label!r}"
            )
        aliases[source_key] = target_label

    metadata_by_chronotopi = {
        Path(source).name: Path(metadata).name
        for source, metadata in data.get("metadata_by_chronotopi", {}).items()
    }
    metadata_relatives: dict[str, dict[str, PersonName]] = {}
    for workbook, links in data.get("metadata_relatives", {}).items():
        relative_names: dict[str, PersonName] = {}
        for relation, target in links.items():
            relation_key = person_taxonomy_key(relation)
            name = PersonName.from_label(_clean_name(target))
            if not relation_key or name is None:
                raise PersonTaxonomyError(
                    "Metadata relative links need a relation and a 'Surname, Given' "
                    f"target: {relation!r} -> {target!r}"
                )
            relative_names[relation_key] = name
        metadata_relatives[Path(workbook).name] = relative_names
    return PersonTaxonomySynonyms(
        aliases=MappingProxyType(aliases),
        metadata_by_chronotopi=MappingProxyType(metadata_by_chronotopi),
        metadata_relatives=MappingProxyType(
            {
                workbook: MappingProxyType(names)
                for workbook, names in metadata_relatives.items()
            }
        ),
    )


def load_person_taxonomy_synonyms(path=None) -> PersonTaxonomySynonyms:
    """Load aliases, chronotopi-to-metadata associations and relative links."""
    source_path = Path(path or PERSON_TAXONOMY_SYNONYMS_PATH).resolve()
    return _read_person_taxonomy_synonyms(str(source_path))


def metadata_relative_name(metadata_source, relation) -> PersonName | None:
    """Return the reviewed Personae person for an unnamed metadata relative."""
    return load_person_taxonomy_synonyms().metadata_relative_name(
        metadata_source, relation
    )


def person_taxonomy_alias(value: str) -> str | None:
    """Return the reviewed canonical Personae label for a source name."""
    return load_person_taxonomy_synonyms().canonical_label(value)


def canonical_person_name(given_name, family_name) -> PersonName | None:
    """Return the reviewed name for a given/family pair, or None when unmapped."""
    for variant in (
        f"{given_name or ''} {family_name or ''}",
        f"{family_name or ''}, {given_name or ''}",
    ):
        target = person_taxonomy_alias(variant)
        name = PersonName.from_label(target) if target else None
        if name is not None:
            return name
    return None


def _clean_name(value) -> str:
    return " ".join(str(value or "").strip().split()).strip(" ,\u2013-")


def is_placeholder_name(value) -> bool:
    """True for empty or unknown name parts such as "?" or "unbekannt"."""
    return _clean_name(value).casefold() in _NAME_PLACEHOLDERS


def _metadata_name_variants(person: Mapping) -> list[str]:
    given_names = [
        _clean_name(person.get("given_name")),
        _clean_name(person.get("previous_given_name")),
    ]
    family_names = [
        _clean_name(person.get("family_name")),
        _clean_name(person.get("previous_family_name")),
    ]
    variants = []
    for given_name in dict.fromkeys(given_names):
        if is_placeholder_name(given_name):
            continue
        for family_name in dict.fromkeys(family_names):
            if is_placeholder_name(family_name):
                continue
            variants.extend(
                PersonName(family_name=family_name, given_name=given_name).variants()
            )
    return list(dict.fromkeys(variants))


def _existing_person_variants(label: str) -> list[str]:
    variants = [label]
    name = PersonName.from_label(label)
    if (
        name is not None
        and name.family_name
        and name.given_name
        and not person_taxonomy_key(name.given_name).endswith(" familie")
    ):
        variants.append(name.natural_order)
    return variants


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


@dataclass(frozen=True)
class PersonaeAugmentation:
    """The Personae taxonomy with person leaves, and the aliases it resolves."""

    taxonomy: Taxonomy
    aliases: Mapping[str, str]


@dataclass(frozen=True)
class _SourceBranch:
    """The metadata surname branch and the people one chronotopi workbook feeds."""

    family_name: str
    labels: frozenset[str]


def augment_personae_taxonomy(
    taxonomy: Taxonomy,
    overview: Mapping[str, Sequence[str]],
    *,
    data_root: str | Path,
    synonyms_path: str | Path | None = None,
) -> PersonaeAugmentation:
    """Add metadata and chronotopi people under their metadata surname branch.

    ``overview`` is the same workbook-path-to-sheet-names map used by the
    chronotopi import. Each workbook must have a reviewed metadata association
    in the JSON mapping so the branch label comes from the main metadata record.
    The returned aliases are normalized source-name keys to canonical Personae
    leaf labels and are intended for :func:`taxonomy_import.import_taxonomy`.
    """
    from metadati import read_person_record

    config = load_person_taxonomy_synonyms(synonyms_path)
    aliases = dict(config.aliases)
    explicit_alias_keys = set(aliases)
    referenced_alias_keys: set[str] = set()
    occurrences = _occurrences_for(taxonomy)

    personae_root_index = next(
        (
            index
            for index, occurrence in enumerate(occurrences)
            if occurrence.parent_index is None
            and _label_key(_extract_key(occurrence.label)) == _label_key("Personae")
        ),
        None,
    )
    if personae_root_index is None:
        personae_root_index = len(occurrences)
        occurrences.append(
            TaxonomyOccurrence(
                label="Personae",
                parent_index=None,
                top_level="Personae",
                path=("Personae",),
            )
        )
    personae_root = occurrences[personae_root_index]

    def register_alias(source: str, target: str) -> None:
        source_key = person_taxonomy_key(source)
        target_label = _clean_name(target)
        if not source_key or not target_label or source_key in explicit_alias_keys:
            return
        previous = aliases.get(source_key)
        if previous and person_taxonomy_key(previous) != person_taxonomy_key(
            target_label
        ):
            raise PersonTaxonomyError(
                f"Source name {source!r} maps to both {previous!r} and {target_label!r}"
            )
        aliases[source_key] = target_label

    def alias_target(source: str) -> str | None:
        key = person_taxonomy_key(source)
        target = aliases.get(key)
        if target is not None:
            referenced_alias_keys.add(key)
        return target

    parent_indexes = {
        occurrence.parent_index
        for occurrence in occurrences
        if occurrence.parent_index is not None
    }
    personae_occurrences = [
        (index, occurrence)
        for index, occurrence in enumerate(occurrences)
        if _is_personae_occurrence(occurrence)
    ]
    person_labels: dict[str, str] = {}
    personae_labels: dict[str, int] = {}
    person_family_by_key: dict[str, str] = {}
    for index, occurrence in personae_occurrences:
        key = person_taxonomy_key(occurrence.label)
        if key:
            personae_labels.setdefault(key, index)
        if (
            index == personae_root_index
            or index in parent_indexes
            or _is_collective_label(occurrence.label)
        ):
            continue
        if key in person_labels and person_labels[key] != occurrence.label:
            raise PersonTaxonomyError(
                f"Personae labels normalize to the same person name: "
                f"{person_labels[key]!r} and {occurrence.label!r}"
            )
        person_labels[key] = occurrence.label
        for variant in _existing_person_variants(occurrence.label):
            register_alias(variant, occurrence.label)

    def ensure_family_branch(family_name: str) -> int:
        family_key = _label_key(family_name)
        matches = [
            index
            for index, occurrence in enumerate(occurrences)
            if occurrence.parent_index == personae_root_index
            and _label_key(occurrence.label) == family_key
        ]
        if len(matches) > 1:
            raise PersonTaxonomyError(
                f"Multiple Personae family branches match {family_name!r}"
            )
        if matches:
            return matches[0]
        normalized_family = person_taxonomy_key(family_name)
        existing_index = personae_labels.get(normalized_family)
        if existing_index is not None:
            raise PersonTaxonomyError(
                f"Cannot create family branch {family_name!r}; a different "
                "Personae node already uses that label"
            )
        index = len(occurrences)
        occurrences.append(
            TaxonomyOccurrence(
                label=family_name,
                parent_index=personae_root_index,
                top_level=personae_root.top_level,
                path=personae_root.path + (family_name,),
            )
        )
        personae_labels[normalized_family] = index
        parent_indexes.add(index)
        return index

    def ensure_person(family_name: str, label: str) -> str:
        clean_label = _clean_name(label)
        key = person_taxonomy_key(clean_label)
        if not key:
            raise PersonTaxonomyError("A Personae person label cannot be empty")
        if key in person_labels:
            canonical = person_labels[key]
            assigned_family = person_family_by_key.get(key)
            if assigned_family is not None and person_taxonomy_key(
                assigned_family
            ) != person_taxonomy_key(family_name):
                raise PersonTaxonomyError(
                    f"Person {canonical!r} is assigned to both the "
                    f"{assigned_family!r} and {family_name!r} family branches"
                )
            parent_index = ensure_family_branch(family_name)
            existing_index = personae_labels[key]
            existing = occurrences[existing_index]
            if existing.parent_index != parent_index:
                parent = occurrences[parent_index]
                occurrences[existing_index] = TaxonomyOccurrence(
                    label=existing.label,
                    parent_index=parent_index,
                    top_level=parent.top_level,
                    path=parent.path + (existing.label,),
                )
            person_family_by_key[key] = family_name
            return canonical
        if key in personae_labels:
            existing = occurrences[personae_labels[key]]
            raise PersonTaxonomyError(
                f"Person label {clean_label!r} collides with an existing "
                f"Personae branch or collective label at {' > '.join(existing.path)!r}"
            )

        parent_index = ensure_family_branch(family_name)
        parent = occurrences[parent_index]
        index = len(occurrences)
        occurrences.append(
            TaxonomyOccurrence(
                label=clean_label,
                parent_index=parent_index,
                top_level=parent.top_level,
                path=parent.path + (clean_label,),
            )
        )
        person_labels[key] = clean_label
        personae_labels[key] = index
        person_family_by_key[key] = family_name
        return clean_label

    def canonical_metadata_name(person: Mapping) -> str | None:
        for variant in _metadata_name_variants(person):
            target = alias_target(variant)
            if target:
                return target
        given_name = _clean_name(person.get("given_name"))
        family_name = _clean_name(person.get("family_name"))
        if not is_placeholder_name(given_name) and not is_placeholder_name(family_name):
            return PersonName(family_name=family_name, given_name=given_name).label
        return None

    def add_metadata_person(
        person: Mapping,
        family_name: str,
    ) -> str | None:
        label = canonical_metadata_name(person)
        if not label:
            return None
        canonical = ensure_person(family_name, label)
        register_alias(canonical, canonical)
        for variant in _metadata_name_variants(person):
            register_alias(variant, canonical)
        return canonical

    source_root = Path(data_root).resolve()
    family_people: dict[str, set[str]] = {}
    source_family_people: dict[str, _SourceBranch] = {}
    for workbook_path, sheet_names in sorted(overview.items()):
        workbook_name = Path(str(workbook_path)).name
        metadata_name = config.metadata_workbook_for(workbook_name)
        if not metadata_name:
            raise PersonTaxonomyError(
                f"No metadata workbook is configured for chronotopi source "
                f"{workbook_name!r}"
            )
        metadata_path = source_root / metadata_name
        if not metadata_path.is_file():
            raise PersonTaxonomyError(
                f"Metadata workbook for {workbook_name!r} was not found: "
                f"{metadata_path}"
            )
        record = read_person_record(metadata_path)
        main_person = record.get("person") or {}
        family_name = _clean_name(main_person.get("family_name"))
        if is_placeholder_name(family_name):
            raise PersonTaxonomyError(
                f"Metadata record {metadata_name!r} has no usable main-person "
                "surname for its Personae family branch"
            )

        people = family_people.setdefault(family_name, set())
        source_people: set[str] = set()
        main_label = add_metadata_person(main_person, family_name)
        if main_label:
            people.add(main_label)
            source_people.add(main_label)
        for relative in record.get("family", []):
            relative_label = add_metadata_person(relative, family_name)
            if relative_label:
                people.add(relative_label)
                source_people.add(relative_label)

        for sheet_name in sheet_names:
            source_name = _clean_name(sheet_name)
            if not source_name or source_name.startswith("_"):
                continue
            target = alias_target(source_name)
            if not target:
                target = person_labels.get(person_taxonomy_key(source_name))
            if not target:
                target = source_name
            canonical = ensure_person(family_name, target)
            register_alias(source_name, canonical)
            people.add(canonical)
            source_people.add(canonical)
        source_family_people[workbook_name] = _SourceBranch(
            family_name=family_name, labels=frozenset(source_people)
        )

    for family_name in sorted(family_people, key=person_taxonomy_key):
        ensure_family_branch(family_name)
        for label in sorted(family_people[family_name], key=person_taxonomy_key):
            ensure_person(family_name, label)

    # Validate by source-file association, not by parsing a person's label or
    # assuming its surname matches the metadata record's surname.
    for workbook_name, branch in source_family_people.items():
        branch_index = ensure_family_branch(branch.family_name)
        for label in branch.labels:
            person_index = personae_labels.get(person_taxonomy_key(label))
            if (
                person_index is None
                or occurrences[person_index].parent_index != branch_index
            ):
                raise PersonTaxonomyError(
                    f"Person {label!r} from chronotopi source {workbook_name!r} "
                    f"is not grouped under its metadata surname branch "
                    f"{branch.family_name!r}"
                )

    occurrences = _parent_first_occurrences(occurrences)
    personae_root_index = next(
        index
        for index, occurrence in enumerate(occurrences)
        if occurrence.parent_index is None
        and _label_key(_extract_key(occurrence.label)) == _label_key("Personae")
    )
    merged = Taxonomy(
        hierarchy=_hierarchy_from_occurrences(occurrences),
        occurrences=tuple(occurrences),
    )
    merged.validate_unique_labels()

    leaf_labels: dict[str, str] = {}
    merged_parent_indexes = {
        occurrence.parent_index
        for occurrence in occurrences
        if occurrence.parent_index is not None
    }
    for index, occurrence in enumerate(occurrences):
        if (
            not _is_personae_occurrence(occurrence)
            or index == personae_root_index
            or index in merged_parent_indexes
            or _is_collective_label(occurrence.label)
        ):
            continue
        key = person_taxonomy_key(occurrence.label)
        previous = leaf_labels.get(key)
        if previous and previous != occurrence.label:
            raise PersonTaxonomyError(
                f"Personae aliases are ambiguous between {previous!r} and "
                f"{occurrence.label!r}"
            )
        leaf_labels[key] = occurrence.label

    normalized_aliases = {}
    for source_key, target in aliases.items():
        target_label = leaf_labels.get(person_taxonomy_key(target))
        if target_label is None:
            if source_key not in referenced_alias_keys:
                continue
            raise PersonTaxonomyError(
                f"Person alias target {target!r} does not identify a Personae "
                "person leaf"
            )
        normalized_aliases[source_key] = target_label

    for label in leaf_labels.values():
        normalized_aliases.setdefault(person_taxonomy_key(label), label)
    return PersonaeAugmentation(taxonomy=merged, aliases=normalized_aliases)
