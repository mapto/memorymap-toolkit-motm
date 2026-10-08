"""Belege (Extraction) import logic.

Reads belege_*.xlsx files and imports their Interviews and Extractions
through the Django REST API.
"""

from __future__ import annotations

from pathlib import Path

from fast_langdetect import detect as detect_language
from openpyxl import load_workbook
from tqdm.auto import tqdm

from api_client import (
    api_bulk_upsert,
    api_get,
    build_interview_payload,
    get_or_create_concept,
    normalize_interview_id,
    parse_interview_id_from_quelle,
    upsert_interviews,
)
from utils import clean_str, is_empty


def read_belege_rows(
    xlsx_path: str | Path, sheet_name: str = "Belege"
) -> list[dict]:
    """Read the Belege sheet into named row dictionaries.

    Keeping column handling here prevents the import orchestration and the
    payload builders from depending on positional Excel indexes.
    """
    workbook = load_workbook(xlsx_path)
    try:
        rows = list(workbook[sheet_name].iter_rows(values_only=True))
    finally:
        workbook.close()

    fields = (
        "identifier", "quelle", "interview_id", "interview_date",
        "interviewee_identifier", "mentioned_persons", "timecode", "concepts",
        "quote", "classification", "event_ids", "event_confidence", "notes",
    )
    named_rows = []
    for row in rows[3:]:
        if not row or all(cell is None for cell in row):
            continue
        cells = (list(row) + [None] * len(fields))[:len(fields)]
        named_rows.append(
            {field: cells[index] for index, field in enumerate(fields)}
        )
    return named_rows


def load_person_map() -> dict[str, int]:
    """Load all source identifiers needed by citation imports."""
    return {
        person["identifier"]: person["id"]
        for person in api_get("persons")
        if person.get("identifier")
    }


def load_interview_map() -> dict[str, int]:
    """Load existing Interview archive IDs for idempotent reimports."""
    return {
        normalize_interview_id(interview["archive_id"]): interview["id"]
        for interview in api_get("interviews")
        if interview.get("archive_id")
    }


def archive_id_for_row(row: dict) -> str | None:
    """Resolve a row's explicit archive ID or derive it from ``quelle``."""
    archive_id = clean_str(row["interview_id"])
    if archive_id:
        return archive_id
    return parse_interview_id_from_quelle(clean_str(row["quelle"]))


def build_row_interview_payload(row: dict, person_map: dict[str, int]) -> dict | None:
    """Build the shared Interview payload for one citation row."""
    return build_interview_payload(
        archive_id_for_row(row),
        interviewee=person_map.get(clean_str(row["interviewee_identifier"])),
        interview_date=row["interview_date"],
    )


def detect_quote_language(quote: str) -> str | None:
    """Detect a quote language when the detector has enough confidence."""
    if len(quote) < 20:
        return None
    try:
        result = detect_language(quote)
        if result and float(result[0]["score"]) > 0.7:
            return str(result[0]["lang"])
    except Exception:
        pass
    return None


def build_extraction_payload(row: dict, person_map: dict[str, int]) -> dict | None:
    """Build one Extraction payload, excluding its Interview foreign key."""
    identifier = clean_str(row["identifier"])
    if not identifier:
        return None

    payload: dict = {
        "identifier": identifier,
        "timecode": clean_str(row["timecode"]),
        "quote": clean_str(row["quote"]),
        "classification": clean_str(row["classification"]),
        "event_confidence": clean_str(row["event_confidence"]),
        "notes": clean_str(row["notes"]),
    }
    language = detect_quote_language(payload["quote"])
    if language:
        payload["language"] = language

    mentioned = clean_str(row["mentioned_persons"])
    if mentioned:
        first_identifier = mentioned.replace("\n", ",").split(",")[0].strip()
        person_id = person_map.get(first_identifier)
        if person_id:
            payload["people_mentioned"] = person_id

    concept_ids = []
    for topic in clean_str(row["concepts"]).split(","):
        if not is_empty(topic):
            concept_id = get_or_create_concept(topic.strip())
            if concept_id:
                concept_ids.append(concept_id)
    if concept_ids:
        payload["concepts"] = concept_ids
    return payload


def prepare_belege_payloads(
    rows: list[dict], person_map: dict[str, int]
) -> tuple[list[dict], list[tuple[str | None, dict]]]:
    """Prepare unique Interview payloads and citation payloads separately."""
    interview_payloads = []
    extraction_payloads = []
    for row in tqdm(rows, desc="Belege", unit="row"):
        interview_payload = build_row_interview_payload(row, person_map)
        if interview_payload:
            interview_payloads.append(interview_payload)
        extraction_payload = build_extraction_payload(row, person_map)
        if extraction_payload:
            extraction_payloads.append(
                (archive_id_for_row(row), extraction_payload)
            )
    return interview_payloads, extraction_payloads


def attach_interview_ids(
    prepared_payloads: list[tuple[str | None, dict]],
    interview_map: dict[str, int],
) -> tuple[list[dict], list[str]]:
    """Add Interview foreign keys to prepared citations and report misses."""
    payloads = []
    errors = []
    for archive_id, payload in prepared_payloads:
        if archive_id:
            interview_id = interview_map.get(archive_id)
            if interview_id:
                payload["interview"] = interview_id
            else:
                errors.append(
                    f"citation {payload['identifier']}: "
                    f"Interview {archive_id} was not created"
                )
        payloads.append(payload)
    return payloads, errors


def bulk_upsert_extractions(payloads: list[dict]) -> tuple[list[int], list[str]]:
    """Write citation payloads in API-sized batches and collect failures."""
    results = []
    errors = []
    for start in range(0, len(payloads), 200):
        try:
            response = api_bulk_upsert("extractions", payloads[start : start + 200])
            imported_items = [
                *response.get("created_items", []),
                *response.get("updated_items", []),
            ]
            results.extend(
                item["id"] for item in imported_items if item.get("id") is not None
            )
            errors.extend(
                f"bulk item {item.get('index', '?')}: {item.get('error', item)}"
                for item in response.get("errors", [])
            )
        except Exception as exc:
            errors.append(f"bulk batch {start}: {exc}")
    return results, errors


def import_belege(xlsx_path: str | Path, sheet_name: str = "Belege") -> list[int]:
    """Import Belege rows and link each citation to its Interview source.

    Interviews are upserted before Extractions because the extraction table
    stores only the Interview foreign key. Rerunning the importer therefore
    also repairs existing citations whose ``interview_id`` was empty.
    """
    xlsx_path = Path(xlsx_path)
    rows = read_belege_rows(xlsx_path, sheet_name)
    person_map = load_person_map()
    interview_map = load_interview_map()
    interview_payloads, prepared_payloads = prepare_belege_payloads(rows, person_map)

    created_interviews, errors = upsert_interviews(interview_payloads)
    interview_map.update(created_interviews)
    payloads, linkage_errors = attach_interview_ids(prepared_payloads, interview_map)
    results, extraction_errors = bulk_upsert_extractions(payloads)
    errors.extend(linkage_errors)
    errors.extend(extraction_errors)

    if errors:
        print(f"\n\u26a0 {len(errors)} errors:")
        for error in errors:
            print(f"  \u274c {error}")
    print(f"\u2705 Imported {len(results)} extractions from {xlsx_path.name}")
    return results
