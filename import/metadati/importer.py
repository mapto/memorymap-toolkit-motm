"""Metadati import flow from workbooks to the API.

This is the entry point of the metadati pipeline. ``import_from_xlsx`` reads one
``metadati_*.xlsx`` workbook with ``sheets.read_person_record`` and passes the
record to ``import_record``. That function writes the record through the other
metadati modules, in this order: the Person, the birth place, the interviews,
and the family relationships. Conflicting dates or birth places raise
``ValueError``, which stops only that record.

Usage, from the ``import`` folder, as in ``metadati.ipynb``::

    from metadati import import_all_metadati, import_from_xlsx

    result = import_all_metadati()  # every metadati_*.xlsx under data/nuove schede
    person_id = import_from_xlsx("path/to/metadati_example.xlsx")

Both calls need an authenticated API session, which the notebook creates with
``api_client.login``. ``import_all_metadati`` continues when one file fails.
"""

from __future__ import annotations

from pathlib import Path
from api_client import BASE_URL, SESSION
from metadati.people import get_or_create_person
from metadati.interviews import create_interview
from metadati.relationships import create_relationship
from metadati.places import get_or_create_location, _maybe_update_person_place
from metadati.sheets import read_person_record


def import_record(record, source_workbook=None):
    """Import one parsed person record through the API and return the Person ID.

    ``import_from_xlsx`` passes in the dict from ``sheets.read_person_record``.
    ``source_workbook`` is the metadata file name and selects the reviewed links
    for unnamed relatives. The steps run in this order: the main Person
    (``people.get_or_create_person``), the birth place (``places``), each
    interview (``interviews.create_interview``), and each family row
    (``relationships.create_relationship``).

    Returns None, after printing a "Skipped" line, when the Person cannot be
    resolved, and then no other step runs. Conflicting birth places or lifespans
    raise ``ValueError``, and an interview write error raises ``RuntimeError``.
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
    """Read one metadati workbook and import it with ``import_record``.

    The file name is passed as ``source_workbook``. Prints a success or skip line
    and returns the Person ID, or None when the Person was skipped. Errors from
    reading the file or from ``import_record`` propagate to the caller. Use this
    for a single workbook, such as the commented-out call in ``metadati.ipynb``.
    """
    record = read_person_record(xlsx_path)
    person_id = import_record(record, source_workbook=Path(xlsx_path).name)
    if person_id:
        print(f"\u2705 Imported: {xlsx_path}")
    else:
        print(f"\u26a0\ufe0f Skipped: {xlsx_path}")
    return person_id


def import_all_metadati(directory=None):
    """Import every metadati_*.xlsx workbook under a folder, one file at a time.

    The default folder is ``data/nuove schede`` at the repository root. Pass
    ``directory`` to use another folder. Files are found recursively in sorted
    order, and names containing "template" are skipped. An exception from one
    file is printed with its file name and does not stop the run. A file that
    fails or is skipped is missing from the returned list of Person IDs.
    ``metadati.ipynb`` calls this function.
    """
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
