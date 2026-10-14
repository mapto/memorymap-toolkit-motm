"""Canonical person names, aliases, and metadata name variants.

These functions answer what the importers ask about a person's name: which
reviewed Personae label a spelling refers to (``person_taxonomy_alias`` and
``canonical_person_name``), who an unnamed relative is
(``metadata_relative_name``), and which spellings to register for a metadata
record or an existing Personae leaf (``_metadata_name_variants`` and
``_existing_person_variants``).

Lookups read the cached synonym table, so repeated calls are cheap and agree
with the JSON as it was first read in the process. The variant helpers feed
``augment_personae_taxonomy``, which uses them to map a spelling such as
"Hedwig Burgheim" to its leaf "Burgheim, Hedwig".
"""

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
    """Return the reviewed name for a given/family pair, or None when unmapped.

    Metadati calls this before it creates or matches a person in the API. The
    pair is tried as ``Given Family`` and then ``Family, Given``; the first variant
    whose reviewed target is a ``Surname, Given`` label is returned as a
    ``PersonName``. When the result differs from the source names, the originals
    are kept as previous names. None means no reviewed form exists, so the source
    names are used unchanged.
    """
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
    """Return every spelling of a metadata person's current and previous names.

    Each given/family pair from the record is expanded into ``Given Family`` and
    ``Family, Given``, so an alias keyed on either spelling, or on a previous
    name, still finds the person. Placeholder parts such as ``unbekannt`` are
    skipped, so unknown names never become aliases. The result is de-duplicated
    and keeps first-seen order.
    """
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
    """Return the spellings under which an existing Personae leaf is registered.

    The label itself is always included. If it parses as ``Surname, Given``, its
    natural ``Given Surname`` order is added too, so a sheet written that way
    resolves to the leaf. Labels whose given part ends in the word ``familie`` get
    only the label, because their natural order would not name a person.
    """
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
