"""Canonical person names, aliases, and metadata name variants."""

from __future__ import annotations

from typing import Mapping
from person_taxonomy.keys import person_taxonomy_key, _clean_name, is_placeholder_name
from person_taxonomy.model import PersonName
from person_taxonomy.synonyms import load_person_taxonomy_synonyms


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
