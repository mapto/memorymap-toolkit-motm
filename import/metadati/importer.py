"""Metadati import flow from workbooks to the API."""

from __future__ import annotations

from pathlib import Path
from api_client import BASE_URL, SESSION
from metadati.people import get_or_create_person
from metadati.interviews import create_interview
from metadati.relationships import create_relationship
from metadati.places import get_or_create_location, _maybe_update_person_place
from metadati.sheets import read_person_record


def import_record(record, source_workbook=None):
    """Import a full person record (parsed JSON) via API calls.

    source_workbook is the metadata file name; it scopes the reviewed relative links.
    """
    person_id = get_or_create_person(
        record["person"],
        identifier=record.get("identifier"),
    )
    if not person_id:
        print("Skipped: invalid person")
        return None

    # Birth place
    birth_place = record.get("birth_place", {})
    location_id = get_or_create_location(birth_place)
    if location_id:
        _maybe_update_person_place(
            person_id,
            "birth_place",
            location_id,
            birth_place.get("name"),
        )

    # Interviews
    for interview_data in record.get("interviews", []):
        create_interview(person_id, interview_data)

    # Family / relationships
    person_data = SESSION.get(f"{BASE_URL}/persons/{person_id}/").json()
    main_family_name = person_data.get("family_name", "")
    for family_data in record.get("family", []):
        create_relationship(person_id, family_data, main_family_name, source_workbook)

    return person_id


def import_from_xlsx(xlsx_path):
    """Parse an xlsx file and import the person record via the API."""
    record = read_person_record(xlsx_path)
    person_id = import_record(record, source_workbook=Path(xlsx_path).name)
    if person_id:
        print(f"\u2705 Imported: {xlsx_path}")
    else:
        print(f"\u26a0\ufe0f Skipped: {xlsx_path}")
    return person_id


def import_all_metadati(directory=None):
    """Find and import all metadati_*.xlsx files from the data directory."""
    if directory is None:
        directory = Path(__file__).resolve().parents[2] / "data" / "nuove schede"
    directory = Path(directory)
    results = []
    for xlsx_path in sorted(directory.rglob("metadati_*.xlsx")):
        if "template" in xlsx_path.name:
            continue
        print(f"\nProcessing: {xlsx_path}")
        try:
            person_id = import_from_xlsx(xlsx_path)
            if person_id:
                results.append(person_id)
        except Exception as e:
            print(f"\u274c ERROR in {xlsx_path.name}: {e}")
    print(f"\n\u2705 Imported {len(results)} valid records")
    return results
