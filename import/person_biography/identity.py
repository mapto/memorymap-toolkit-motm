"""Identity keys for matching biographies to people."""

from __future__ import annotations

from typing import Any, Mapping
from person_taxonomy import person_taxonomy_key
from utils import clean_str


def _clean_name(value: Any) -> str:
    return " ".join(clean_str(value).split()).strip(" ,")


def _alias_target(name: str, aliases: Mapping[str, str]) -> str | None:
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
    result: dict[str, list[Mapping[str, Any]]] = {}
    for person in people:
        identity = _api_identity(person, aliases)
        if identity:
            result.setdefault(identity, []).append(person)
    return result
