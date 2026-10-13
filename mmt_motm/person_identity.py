"""Canonical person-name helpers shared by Person-facing views."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings


PERSON_SYNONYMS_PATH = (
    Path(str(settings.BASE_DIR)) / "data" / "person_taxonomy_synonyms.json"
)


def person_name_key(value: str | None) -> str:
    """Normalize a person name for identity matching without token reordering."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", normalized).split())


@lru_cache(maxsize=1)
def person_name_aliases() -> dict[str, str]:
    """Return the reviewed source-name to canonical Personae-label mapping."""
    if not PERSON_SYNONYMS_PATH.is_file():
        return {}
    data = json.loads(PERSON_SYNONYMS_PATH.read_text(encoding="utf-8"))
    return {
        person_name_key(source): str(target).strip()
        for source, target in data.get("aliases", {}).items()
        if person_name_key(source) and str(target).strip()
    }


def _person_name_variants(person) -> list[str]:
    given_names = [person.given_name, person.previous_given_name]
    family_names = [person.family_name, person.previous_family_name]
    variants = []
    for given_name in dict.fromkeys(name for name in given_names if name):
        for family_name in dict.fromkeys(name for name in family_names if name):
            variants.extend(
                (
                    f"{given_name} {family_name}",
                    f"{family_name}, {given_name}",
                )
            )
    return variants


def canonical_person_label(person) -> str:
    """Resolve a Person row to its reviewed Personae label when available."""
    aliases = person_name_aliases()
    for variant in _person_name_variants(person):
        target = aliases.get(person_name_key(variant))
        if target:
            return target
    if person.family_name and person.given_name:
        return f"{person.family_name}, {person.given_name}"
    return person.given_name or person.family_name or ""


def canonical_person_key(person) -> str:
    return person_name_key(canonical_person_label(person))


@lru_cache(maxsize=1)
def _canonical_alias_keys() -> set[str]:
    return {
        person_name_key(target)
        for target in person_name_aliases().values()
        if person_name_key(target)
    }


def person_deduplication_key(person) -> str:
    """Return a shared key only for identities linked by reviewed aliases."""
    aliases = person_name_aliases()
    for variant in _person_name_variants(person):
        target = aliases.get(person_name_key(variant))
        if target:
            return person_name_key(target)

    canonical_key = canonical_person_key(person)
    if canonical_key in _canonical_alias_keys():
        return canonical_key
    return f"record:{person.pk}"


def _representative_score(person) -> tuple[int, int, int]:
    canonical_label_key = person_name_key(canonical_person_label(person))
    current_label_key = person_name_key(
        f"{person.family_name}, {person.given_name}"
        if person.family_name and person.given_name
        else person.given_name or person.family_name
    )
    return (
        0 if current_label_key == canonical_label_key else 1,
        0 if person.identifier else 1,
        person.pk,
    )


def deduplicate_people(people):
    """Keep one representative Person row per reviewed/canonical identity.

    A record whose current fields match the canonical label is preferred, then
    one carrying an external identifier, then the lowest primary key. Input
    order is preserved for the selected representatives.
    """
    representatives = {}
    for person in people:
        identity = person_deduplication_key(person)
        score = _representative_score(person)
        previous = representatives.get(identity)
        if previous is None or score < previous[0]:
            representatives[identity] = (score, person)
    selected_ids = {person.pk for _, person in representatives.values()}
    return [person for person in people if person.pk in selected_ids]


def get_person_representative(person):
    """Return the same alias-aware representative used by list/tree views."""
    identity = person_deduplication_key(person)
    if identity.startswith("record:"):
        return person

    from .models import Person

    candidates = Person.objects.only(
        "pk",
        "given_name",
        "previous_given_name",
        "family_name",
        "previous_family_name",
        "identifier",
    ).order_by("pk")
    matches = [
        candidate
        for candidate in candidates
        if person_deduplication_key(candidate) == identity
    ]
    if not matches:
        return person
    return min(matches, key=_representative_score)
