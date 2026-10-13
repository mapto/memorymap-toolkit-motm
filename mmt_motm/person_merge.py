"""Transactional merging of duplicate Person records."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from .models import Extraction, Interview, Person, Relationship


class PersonMergeError(ValueError):
    """Raised when two Person records cannot be merged without data loss."""


_SCALAR_FIELDS = (
    "previous_given_name",
    "previous_family_name",
    "gender",
    "education",
    "occupation_at_emigration",
    "occupation_at_source",
    "residence_at_source",
)


def _merge_person_fields(canonical: Person, duplicate: Person) -> list[str]:
    updated_fields = []
    if not canonical.identifier and duplicate.identifier:
        canonical.identifier = duplicate.identifier
        updated_fields.append("identifier")

    if not canonical.previous_given_name:
        previous_given_name = duplicate.previous_given_name
        if not previous_given_name and duplicate.given_name != canonical.given_name:
            previous_given_name = duplicate.given_name
        if previous_given_name:
            canonical.previous_given_name = previous_given_name
            updated_fields.append("previous_given_name")

    if not canonical.previous_family_name:
        previous_family_name = duplicate.previous_family_name
        if not previous_family_name and duplicate.family_name != canonical.family_name:
            previous_family_name = duplicate.family_name
        if previous_family_name:
            canonical.previous_family_name = previous_family_name
            updated_fields.append("previous_family_name")

    for field in _SCALAR_FIELDS[2:]:
        if not getattr(canonical, field) and getattr(duplicate, field):
            setattr(canonical, field, getattr(duplicate, field))
            updated_fields.append(field)

    for field in ("lifespan", "birth_place", "death_place"):
        if getattr(canonical, f"{field}_id") is None and getattr(
            duplicate, f"{field}_id"
        ) is not None:
            setattr(canonical, f"{field}_id", getattr(duplicate, f"{field}_id"))
            updated_fields.append(f"{field}_id")

    return updated_fields


def _merge_translations(canonical: Person, duplicate: Person) -> None:
    for source in duplicate.translations.all():
        target, created = canonical.translations.get_or_create(
            language_code=source.language_code,
            defaults={"description": source.description},
        )
        if not created and not target.description and source.description:
            target.description = source.description
            target.save(update_fields=["description"])


def _merge_relationships(canonical: Person, duplicate: Person) -> None:
    relationships = Relationship.objects.select_for_update().filter(
        Q(person_from=duplicate) | Q(person_to=duplicate)
    )
    for relationship in relationships:
        person_from_id = (
            canonical.pk
            if relationship.person_from_id == duplicate.pk
            else relationship.person_from_id
        )
        person_to_id = (
            canonical.pk
            if relationship.person_to_id == duplicate.pk
            else relationship.person_to_id
        )
        if person_from_id == person_to_id:
            relationship.delete()
            continue

        match = Relationship.objects.filter(
            relationship_type_id=relationship.relationship_type_id,
            timespan_id=relationship.timespan_id,
            person_from_id=person_from_id,
            person_to_id=person_to_id,
            description=relationship.description,
        ).exclude(pk=relationship.pk).first()
        if match:
            match.urls.add(*relationship.urls.all())
            relationship.delete()
            continue

        relationship.person_from_id = person_from_id
        relationship.person_to_id = person_to_id
        relationship.save(update_fields=["person_from", "person_to"])


def merge_person_records(canonical_id: int, duplicate_ids) -> tuple[Person, list[int]]:
    """Merge duplicate Person rows into ``canonical_id`` and move all links.

    Person identifiers are unique and cannot be silently discarded. If both
    records have different identifiers, the transaction is rejected so the
    caller can review the conflict rather than lose an archive identity.
    """
    ids = list(dict.fromkeys(int(value) for value in duplicate_ids))
    ids = [person_id for person_id in ids if person_id != int(canonical_id)]
    with transaction.atomic():
        canonical = Person.objects.select_for_update().get(pk=canonical_id)
        duplicates = list(
            Person.objects.select_for_update()
            .filter(pk__in=ids)
            .order_by("pk")
        )
        found_ids = {person.pk for person in duplicates}
        missing_ids = set(ids) - found_ids
        if missing_ids:
            raise PersonMergeError(
                f"Person records not found for merge: {sorted(missing_ids)}"
            )

        identifiers = {
            identifier
            for identifier in [
                canonical.identifier,
                *(duplicate.identifier for duplicate in duplicates),
            ]
            if identifier
        }
        if len(identifiers) > 1:
            raise PersonMergeError(
                f"Cannot merge Person records with conflicting identifiers: "
                f"{sorted(identifiers)}"
            )

        merged_ids = []
        for duplicate in duplicates:
            updated_fields = _merge_person_fields(canonical, duplicate)
            canonical.urls.add(*duplicate.urls.all())
            _merge_translations(canonical, duplicate)

            for event in duplicate.events.all():
                event.persons.add(canonical)
            Extraction.objects.filter(people_mentioned=duplicate).update(
                people_mentioned=canonical
            )
            Interview.objects.filter(interviewee=duplicate).update(
                interviewee=canonical
            )
            Interview.objects.filter(interviewer=duplicate).update(
                interviewer=canonical
            )
            _merge_relationships(canonical, duplicate)

            duplicate_id = duplicate.pk
            duplicate.delete()
            if updated_fields:
                canonical.save(update_fields=list(dict.fromkeys(updated_fields)))
            merged_ids.append(duplicate_id)

        return canonical, merged_ids
