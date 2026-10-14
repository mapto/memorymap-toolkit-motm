"""Merging reviewed person names into the Personae taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from taxonomy import Taxonomy, TaxonomyOccurrence, _extract_key, _label_key
from person_taxonomy.keys import person_taxonomy_key, _clean_name, is_placeholder_name
from person_taxonomy.model import PersonTaxonomyError, PersonName
from person_taxonomy.synonyms import load_person_taxonomy_synonyms
from person_taxonomy.names import _metadata_name_variants, _existing_person_variants
from person_taxonomy.hierarchy import (
    _occurrences_for,
    _hierarchy_from_occurrences,
    _parent_first_occurrences,
    _is_personae_occurrence,
    _is_collective_label,
)


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
