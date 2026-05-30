"""Belege (Extraction) import logic.

Reads belege_*.xlsx files and imports them into the Extraction model
via the Django REST API.
"""

from __future__ import annotations

from pathlib import Path

from fast_langdetect import detect as detect_language
from openpyxl import load_workbook
from tqdm.auto import tqdm

from api_client import (
    api_bulk_update,
    api_bulk_upsert,
    api_get,
    get_or_create_concept,
    parse_interview_id_from_quelle,
)
from utils import clean_str, is_empty


def import_belege(xlsx_path: str | Path, sheet_name: str = "Belege") -> list[int]:
    """Import all rows from a belege xlsx file via the API."""
    xlsx_path = Path(xlsx_path)
    wb = load_workbook(xlsx_path)
    sheet = wb[sheet_name]

    # Count data rows (skip first 3: title, blank, header)
    all_rows = list(sheet.iter_rows(values_only=True))
    data_rows = [r for r in all_rows[3:] if r and not all(cell is None for cell in r)]

    # Pre-fetch lookup tables once
    existing_extractions = {e["identifier"] for e in api_get("extractions")}
    all_persons = api_get("persons")
    person_map = {p["identifier"]: p["id"] for p in all_persons if p.get("identifier")}
    all_interviews = api_get("interviews")
    interview_map = {
        i["archive_id"]: i["id"] for i in all_interviews if i.get("archive_id")
    }

    payloads: list[dict] = []
    interviewee_updates: dict[int, int] = {}  # interview_id → person_id
    errors: list[str] = []

    for row in tqdm(data_rows, desc=xlsx_path.stem, unit="row"):
        cells = (list(row) + [None] * 13)[:13]
        beleg_id = clean_str(cells[0])  # identifier
        quelle = clean_str(cells[1])  # source reference (Markdown link)
        interview_id = clean_str(cells[2])  # interview archive_id
        # cells[3]: interview_datum (informational only)
        quelle_sprecher = clean_str(cells[4])  # speaker → Interview.interviewee
        betrifft = clean_str(cells[5])  # people mentioned (person identifiers)
        timecode = clean_str(cells[6])  # timecode
        themen = clean_str(cells[7])  # topics/concepts
        zitat = clean_str(cells[8])  # quote
        markierung = clean_str(cells[9])  # classification
        # cells[10]: event_ids (not yet linked)
        event_confidence = clean_str(cells[11])
        notizen = clean_str(cells[12])  # notes

        if is_empty(beleg_id) or beleg_id in existing_extractions:
            continue

        # Resolve person mentioned (first identifier)
        person_id = None
        if betrifft:
            first_pid = betrifft.split(",")[0].strip()
            person_id = person_map.get(first_pid)

        # Resolve interview from pre-fetched map
        archive_id = interview_id if not is_empty(interview_id) else None
        if not archive_id and quelle:
            archive_id = parse_interview_id_from_quelle(quelle)
        interview_db_id = interview_map.get(archive_id) if archive_id else None

        # Collect speaker → interviewee links for batch update
        if not is_empty(quelle_sprecher) and interview_db_id:
            speaker_person_id = person_map.get(quelle_sprecher)
            if speaker_person_id:
                interviewee_updates[interview_db_id] = speaker_person_id

        # Resolve all concepts (uses internal cache)
        concept_ids = []
        if themen:
            for topic in themen.split(","):
                topic = topic.strip()
                if not is_empty(topic):
                    cid = get_or_create_concept(topic)
                    if cid:
                        concept_ids.append(cid)

        payload: dict = {
            "identifier": beleg_id,
            "timecode": timecode,
            "quote": zitat,
            "classification": markierung,
            "event_confidence": event_confidence,
            "notes": notizen,
        }
        # Detect language (only if long enough and confidence > 70%)
        if len(zitat) >= 20:
            try:
                lang_result = detect_language(zitat)
                if lang_result and float(lang_result[0]["score"]) > 0.7:
                    payload["language"] = str(lang_result[0]["lang"])
            except Exception:
                pass
        if person_id:
            payload["people_mentioned"] = person_id
        if interview_db_id:
            payload["interview"] = interview_db_id
        if concept_ids:
            payload["concepts"] = concept_ids

        payloads.append(payload)

    # Bulk-upsert all extractions
    results: list[int] = []
    if payloads:
        BATCH = 200
        for i in range(0, len(payloads), BATCH):
            batch = payloads[i : i + BATCH]
            try:
                resp = api_bulk_upsert("extractions", batch)
                results.extend(item["id"] for item in resp.get("items", []))
            except Exception as e:
                errors.append(f"bulk batch {i}: {e}")

    # Bulk-update interview.interviewee links
    if interviewee_updates:
        updates = [
            {"id": iid, "interviewee": pid} for iid, pid in interviewee_updates.items()
        ]
        try:
            api_bulk_update("interviews", updates)
        except Exception as e:
            errors.append(f"interviewee bulk update: {e}")

    if errors:
        print(f"\n\u26a0 {len(errors)} errors:")
        for err in errors:
            print(f"  \u274c {err}")
    print(f"\u2705 Imported {len(results)} extractions from {xlsx_path.name}")
    return results
