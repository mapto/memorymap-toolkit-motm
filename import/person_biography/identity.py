"""Identity keys for matching biographies to people.

Chronotopi sheets, metadati workbooks, and Memory Map Person records can name the
same person differently. A sheet title may read ``Given Surname``, a workbook
label may read ``Surname, Given``, and a Person may carry a previous name. One
comparison key per person makes these matchable. The keys use the reviewed
aliases from ``person_taxonomy_synonyms.json``, which callers pass in. Without an
alias, a name keeps the order in which it was written, so no token order is
guessed.

The plan step uses ``_identity_from_name`` for sheet titles and
``_identity_from_person_fields`` for metadati people. The validate step uses
``_people_by_identity`` to index the Person records it has fetched. Nothing in
this module reads or writes the API.
"""

from __future__ import annotations

from typing import Any, Mapping
from person_taxonomy import person_taxonomy_key
from utils import clean_str


def _clean_name(value: Any) -> str:
    return " ".join(clean_str(value).split()).strip(" ,")


def _alias_target(name: str, aliases: Mapping[str, str]) -> str | None:
    """Return the reviewed canonical label that ``name`` maps to, or None.

    ``aliases`` maps normalized source spellings to canonical labels, usually
    ``Surname, Given``. A direct key match wins. Otherwise ``name`` is compared
    with each canonical label, both as written and with its parts swapped to
    ``Given Surname``, which finds a reversed spelling and its reviewed target.
    Without this, a sheet title and a metadata label for the same person would
    get two identities.
    """
    key = person_taxonomy_key(name)
    target = aliases.get(key)
    if target:
        return target
    for canonical in aliases.values():
        if key == person_taxonomy_key(canonical):
            return canonical
        if "," in canonical:
            family_name, given_name = (part.strip() for part in canonical.split(",", 1))
            if key == person_taxonomy_key(f"{given_name} {family_name}"):
                return canonical
    return None


def _identity_from_name(name: str, aliases: Mapping[str, str]) -> str:
    cleaned = _clean_name(name)
    target = _alias_target(cleaned, aliases)
    return person_taxonomy_key(target or cleaned)


def _identity_from_person_fields(
    person: Mapping[str, Any], aliases: Mapping[str, str]
) -> str | None:
    """Return the identity key for a Person-shaped record, or None if unnamed.

    ``person`` is a metadati person record or an API Person dict, optionally with
    previous names. Each given and family pair, in both orders, is tried against
    the aliases first, so a Person stored under a former name still matches its
    sheet. Without an alias match, the key is the first non-empty given name and
    family name, current names before previous ones. Returns None when all name
    parts are empty, so the caller can skip unnamed relatives.
    """
    given_names = [
        _clean_name(person.get("given_name")),
        _clean_name(person.get("previous_given_name")),
    ]
    family_names = [
        _clean_name(person.get("family_name")),
        _clean_name(person.get("previous_family_name")),
    ]
    for given_name in dict.fromkeys(name for name in given_names if name):
        for family_name in dict.fromkeys(name for name in family_names if name):
            for variant in (
                f"{given_name} {family_name}",
                f"{family_name}, {given_name}",
            ):
                target = _alias_target(variant, aliases)
                if target:
                    return person_taxonomy_key(target)
    given_name = next((name for name in given_names if name), "")
    family_name = next((name for name in family_names if name), "")
    fallback = " ".join(part for part in (given_name, family_name) if part)
    return person_taxonomy_key(fallback) if fallback else None


def _api_identity(person: Mapping[str, Any], aliases: Mapping[str, str]):
    return _identity_from_person_fields(person, aliases)


def _people_by_identity(people, aliases):
    """Index Person records by identity key, keeping every record per key.

    The validate step passes in the Person list it has already fetched, so the
    match happens in memory. Records with no usable name are left out. Returns a
    dict from key to a list of records. Two records can share a key when Memory
    Map holds duplicates, and all of them are kept so each one is checked.
    """
    result: dict[str, list[Mapping[str, Any]]] = {}
    for person in people:
        identity = _api_identity(person, aliases)
        if identity:
            result.setdefault(identity, []).append(person)
    return result
