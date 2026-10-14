"""Person lookup and creation from metadati records.

A metadati record refers to people who may already exist in the Memory Map API:
the main person, interviewers named in the sources, and relatives in the family
table. ``get_or_create_person`` returns the existing Person when it can find
one, and creates the Person otherwise. Matching by identifier and by name is what
lets an import be repeated without entering the same person twice.

Names are first normalized through the reviewed Personae names in
``person_taxonomy``. ``PERSON_METADATA_FIELDS`` lists the workbook fields that
are copied onto the Person record. Lifespans are handled by ``timespans``, and
HTTP calls go through ``api_client``. The callers are ``importer``,
``interviews``, and ``relationships``.
"""

from __future__ import annotations

from api_client import api_get, api_patch, api_post
from utils import is_empty
from person_taxonomy import canonical_person_name, person_taxonomy_alias
from metadati.timespans import get_or_create_timespan, _maybe_update_lifespan

_person_cache: dict = {}

PERSON_METADATA_FIELDS = (
    "education",
    "occupation_at_emigration",
    "occupation_at_source",
    "residence_at_source",
)


def get_or_create_person(data, identifier=None):
    """Match or create a Person from one name record and return its ID.

    ``data`` holds the names, dates, gender, and metadata of one person. The
    names are first replaced by their reviewed forms from ``person_taxonomy``,
    and the source spelling is kept as a previous name when it differs. A
    reviewed alias is resolved first, through ``api_client.get_person_id``.
    Otherwise, with an identifier, the Person is found by identifier, or by a
    case-insensitive name match among Persons without one, which then receives
    the identifier. Without an identifier, the local cache is checked first, then
    the name match. A match has its lifespan and fields updated, and an unmatched
    person is created. Returns None when neither name part is present.
    """
    source_given_name = data.get("given_name")
    source_family_name = data.get("family_name")
    canonical = canonical_person_name(source_given_name, source_family_name)
    if canonical is not None:
        given_name, family_name = canonical.given_name, canonical.family_name
    else:
        given_name, family_name = source_given_name, source_family_name
    if (given_name, family_name) != (source_given_name, source_family_name):
        data = dict(data)
        if (
            not data.get("previous_given_name")
            and source_given_name
            and source_given_name != given_name
        ):
            data["previous_given_name"] = source_given_name
        if (
            not data.get("previous_family_name")
            and source_family_name
            and source_family_name != family_name
        ):
            data["previous_family_name"] = source_family_name
        data["given_name"] = given_name
        data["family_name"] = family_name
    source_name = " ".join(
        part for part in (source_given_name, source_family_name) if part
    )
    alias_target = person_taxonomy_alias(source_name)

    if is_empty(given_name) and is_empty(family_name):
        return None

    def metadata_payload():
        """Return the non-empty workbook metadata fields for a Person payload.

        This covers ``PERSON_METADATA_FIELDS`` and the persecution group, which
        becomes ``description``. Empty cells are left out, so an empty cell never
        clears a stored value. A non-empty value is sent and replaces the stored
        one.
        """
        payload = {
            field: data[field]
            for field in PERSON_METADATA_FIELDS
            if not is_empty(data.get(field))
        }
        prosecuted_group = data.get("attributes", {}).get("ns_persecution_group")
        if not is_empty(prosecuted_group):
            payload["description"] = prosecuted_group
        return payload

    def update_existing(existing):
        """Send one PATCH with the workbook values for a matched Person.

        ``existing`` is the Person dict from the API. Gender, identifier, and
        previous names are filled only where the stored Person has none. Given and
        family names are set to the resolved names when they differ. The metadata
        fields from ``metadata_payload`` are always included. The PATCH is sent
        only when the patch is non-empty.
        """
        patch = metadata_payload()
        if existing:
            if data.get("gender") and not existing.get("gender"):
                patch["gender"] = data["gender"]
            if identifier and not existing.get("identifier"):
                patch["identifier"] = identifier
            if existing.get("given_name") != given_name:
                patch["given_name"] = given_name or ""
            if existing.get("family_name") != family_name:
                patch["family_name"] = family_name or ""
            if data.get("previous_given_name") and not existing.get(
                "previous_given_name"
            ):
                patch["previous_given_name"] = data["previous_given_name"]
            if data.get("previous_family_name") and not existing.get(
                "previous_family_name"
            ):
                patch["previous_family_name"] = data["previous_family_name"]
        if patch:
            api_patch("persons", existing["id"], patch)

    if alias_target:
        from api_client import get_person_id

        person_id = get_person_id(source_name, source_name, identifier=identifier)
        if not person_id:
            return None
        existing = api_get(f"persons/{person_id}")
        _maybe_update_lifespan(person_id, data)
        update_existing(existing)
        _person_cache[(given_name or "").lower(), (family_name or "").lower()] = (
            person_id
        )
        return person_id

    # Match on identifier
    if identifier:
        existing = api_get("persons", params={"search": identifier})
        match = next((p for p in existing if p.get("identifier") == identifier), None)
        if not match and not is_empty(given_name) and not is_empty(family_name):
            existing = api_get("persons", params={"search": family_name})
            match = next(
                (
                    p
                    for p in existing
                    if not p.get("identifier")
                    and p.get("given_name", "").casefold() == given_name.casefold()
                    and p.get("family_name", "").casefold() == family_name.casefold()
                ),
                None,
            )
            if match:
                api_patch("persons", match["id"], {"identifier": identifier})
        if match:
            key = (match["given_name"].lower(), match["family_name"].lower())
            _person_cache[key] = match["id"]
            _maybe_update_lifespan(match["id"], data)
            update_existing(match)
            return match["id"]
        payload = {
            "identifier": identifier,
            "given_name": given_name or "",
            "family_name": family_name or "",
        }
        payload.update(metadata_payload())
        lifespan_id = get_or_create_timespan(
            start=data.get("birth_date"),
            end=data.get("death_date"),
        )
        if lifespan_id:
            payload["lifespan"] = lifespan_id
        if data.get("gender"):
            payload["gender"] = data["gender"]
        if data.get("previous_given_name"):
            payload["previous_given_name"] = data["previous_given_name"]
        if data.get("previous_family_name"):
            payload["previous_family_name"] = data["previous_family_name"]
        if data.get("attributes", {}).get("ns_persecution_group"):
            payload["description"] = data["attributes"]["ns_persecution_group"]
        created = api_post("persons", payload)
        key = ((given_name or "").lower(), (family_name or "").lower())
        _person_cache[key] = created["id"]
        return created["id"]

    # Check local cache first
    key = ((given_name or "").lower(), (family_name or "").lower())
    if not is_empty(given_name) and not is_empty(family_name):
        if key in _person_cache:
            _maybe_update_lifespan(_person_cache[key], data)
            api_patch("persons", _person_cache[key], metadata_payload())
            return _person_cache[key]

    # Match on name (case-insensitive) via API
    if not is_empty(given_name) and not is_empty(family_name):
        existing = api_get("persons", params={"search": family_name})
        for p in existing:
            if (
                p["given_name"].lower() == given_name.lower()
                and p["family_name"].lower() == family_name.lower()
            ):
                _person_cache[key] = p["id"]
                _maybe_update_lifespan(p["id"], data)
                update_existing(p)
                return p["id"]

    payload = {
        "given_name": given_name or "",
        "family_name": family_name or "",
    }
    payload.update(metadata_payload())
    if data.get("gender"):
        payload["gender"] = data["gender"]
    lifespan_id = get_or_create_timespan(
        start=data.get("birth_date"),
        end=data.get("death_date"),
    )
    if lifespan_id:
        payload["lifespan"] = lifespan_id
    created = api_post("persons", payload)
    key = ((given_name or "").lower(), (family_name or "").lower())
    _person_cache[key] = created["id"]
    return created["id"]
