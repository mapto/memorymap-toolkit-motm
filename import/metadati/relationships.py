"""Relationship types and person-to-person links.

The family table of a metadati sheet names each relative with a German relation
label, such as "Mutter" or "Onkel väterl". ``RELATIONSHIP_MAP`` translates the
common labels into English relationship-type names, and other labels are stored
under their cleaned text. Each relative is resolved to a Person by
``people.get_or_create_person``, and a Relationship is created from the main
person to that relative.

A relative who appears only as a placeholder name, such as "?", can be linked to
a reviewed Personae person. The link is keyed by workbook file name and relation
label. Placeholder duplicates of the same relative are then merged into that
person. ``importer.import_record`` calls ``create_relationship`` for each row.
"""

from __future__ import annotations

from api_client import api_get, api_patch, api_post
from utils import is_empty
from person_taxonomy import is_placeholder_name, metadata_relative_name
from metadati.values import clean_label
from metadati.people import get_or_create_person


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELATIONSHIP_MAP = {
    "vater": "father",
    "mutter": "mother",
    "schwester": "sister",
    "bruder": "brother",
    "großvater": "grandfather",
    "grossvater": "grandfather",
    "großvater väterlicherseits": "paternal grandfather",
    "grossvater väterlicherseits": "paternal grandfather",
    "großvater väterl": "paternal grandfather",
    "großmutter väterlicherseits": "paternal grandmother",
    "großmutter väterl": "paternal grandmother",
    "grossmutter väterlicherseits": "paternal grandmother",
    "großmutter mütterlicherseits": "maternal grandmother",
    "grossmutter mütterlicherseits": "maternal grandmother",
    "großmutter mütt": "maternal grandmother",
    "großvater mütterlicherseits": "maternal grandfather",
    "großvater mütt": "maternal grandfather",
    "tante": "aunt",
    "onkel": "uncle",
    "onkel väterl": "paternal uncle",
    "bruder aus erster ehe": "brother from the first marriage",
    "halbschwester": "half sister",
    "1 frau erste ehe": "first wife",
    "stiefmutter": "stepmother",
    "cousin": "cousin",
    "vetter": "cousin",
    "cousine": "cousin",
    "base": "cousin",
}
_relationship_type_cache: dict = {}
_relationship_cache: dict = {}


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------


def get_or_create_relationship_type(label):
    """Return the RelationshipType ID for a relation label, creating it if needed.

    Returns None for an empty label. The label is cleaned with ``clean_label`` and
    translated through ``RELATIONSHIP_MAP``, so German terms such as "vater"
    become "father". Other labels keep their cleaned text as the name, and the
    workbook wording is stored as ``original_label`` when a type is created. IDs
    are cached per process. Side effects: API GET and, when missing, POST.
    """
    if is_empty(label):
        return None

    label_clean = clean_label(label)
    mapped = RELATIONSHIP_MAP.get(label_clean, label_clean)

    if mapped in _relationship_type_cache:
        return _relationship_type_cache[mapped]

    existing = api_get("relationship-types", params={"search": mapped})
    match = next((rt for rt in existing if rt["name"] == mapped), None)
    if match:
        _relationship_type_cache[mapped] = match["id"]
        return match["id"]

    created = api_post(
        "relationship-types",
        {
            "name": mapped,
            "original_label": label.strip(),
        },
    )
    _relationship_type_cache[mapped] = created["id"]
    return created["id"]


def _is_unnamed_relative(person, family_name):
    """Return True when a stored Person is a placeholder for the same relative.

    The given name must be a placeholder, as judged by
    ``person_taxonomy.is_placeholder_name``, for example "?" or "unbekannt". The
    stored family name must then be a placeholder too, or equal ``family_name``
    ignoring case and surrounding spaces. Used by ``_merge_unnamed_relatives``
    to find duplicates.
    """
    if not is_placeholder_name(person.get("given_name")):
        return False
    stored_family = person.get("family_name")
    return is_placeholder_name(stored_family) or (
        str(stored_family).strip().casefold() == family_name.casefold()
    )


def _merge_unnamed_relatives(
    main_person_id, rel_type_id, canonical_id, given_name, family_name
):
    """Merge placeholder duplicates of a linked relative into the canonical person.

    Called by ``create_relationship`` only after a reviewed link was found. The
    duplicates are the other Persons that the main person relates to with the same
    relation type, that match ``_is_unnamed_relative``, and that have no
    identifier. Each duplicate is first renamed to ``given_name`` and
    ``family_name``. The backend merge (``person_merge.merge_person_records``)
    copies a differing name into an empty previous-name field of the canonical
    Person, and the rename keeps the placeholder out of those fields. Records with
    an identifier are never merged automatically. Side effects: API GET of
    relationships and persons, a PATCH of each duplicate, and one merge POST. No
    PATCH or merge is sent when there are no duplicates.
    """
    duplicate_ids = []
    for relationship in api_get("relationships"):
        if (
            relationship["person_from"] != main_person_id
            or relationship["relationship_type"] != rel_type_id
            or relationship["person_to"] in (canonical_id, *duplicate_ids)
        ):
            continue
        candidate = api_get(f"persons/{relationship['person_to']}")
        if candidate.get("identifier") or not _is_unnamed_relative(
            candidate, family_name
        ):
            continue
        duplicate_ids.append(candidate["id"])
    if not duplicate_ids:
        return
    for duplicate_id in duplicate_ids:
        api_patch(
            "persons",
            duplicate_id,
            {"given_name": given_name, "family_name": family_name},
        )
    api_post(f"persons/{canonical_id}/merge", {"duplicate_ids": duplicate_ids})


def create_relationship(
    main_person_id, data, fallback_family_name, source_workbook=None
):
    """Create or reuse the Relationship from the main Person to one relative.

    ``data`` is one row of the family table, and ``fallback_family_name`` is the
    main Person's family name, used when the row has none. A placeholder name is
    replaced by the reviewed Personae person for ``source_workbook`` and the row's
    relation label, when such a link exists, and that person's placeholder
    duplicates are then merged into it. The notes column becomes the description.
    An existing Relationship between the same two people with the same type is
    reused. Returns the Relationship ID, or None when the row has no relation or
    the relative or type cannot be resolved. Side effects: API GET and POST calls,
    plus the merge described above.
    """
    if is_empty(data.get("relation")):
        return None

    given_name = data.get("given_name")
    family_name = data.get("family_name")
    if is_empty(family_name):
        family_name = fallback_family_name

    linked_name = None
    if is_placeholder_name(given_name):
        linked_name = metadata_relative_name(source_workbook, data.get("relation"))
    if linked_name is not None:
        given_name = linked_name.given_name
        family_name = linked_name.family_name

    related_id = get_or_create_person(
        {
            "given_name": given_name,
            "family_name": family_name,
            "birth_date": data.get("birth_date"),
            "death_date": data.get("death_date"),
        }
    )
    if not related_id:
        return None

    rel_type_id = get_or_create_relationship_type(data.get("relation"))
    if not rel_type_id:
        return None

    if linked_name:
        _merge_unnamed_relatives(
            main_person_id, rel_type_id, related_id, given_name, family_name
        )

    # Check local cache first
    cache_key = (main_person_id, related_id, rel_type_id)
    if cache_key in _relationship_cache:
        return _relationship_cache[cache_key]

    # Check for existing relationship via API
    existing = api_get("relationships")
    for r in existing:
        if (
            r["person_from"] == main_person_id
            and r["person_to"] == related_id
            and r["relationship_type"] == rel_type_id
        ):
            _relationship_cache[cache_key] = r["id"]
            return r["id"]

    created = api_post(
        "relationships",
        {
            "relationship_type": rel_type_id,
            "person_from": main_person_id,
            "person_to": related_id,
            "description": data.get("notes") or "",
        },
    )
    _relationship_cache[cache_key] = created["id"]
    return created["id"]
