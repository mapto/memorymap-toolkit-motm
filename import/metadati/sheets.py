"""Workbook sheet parsers for metadati person records."""

from __future__ import annotations

import re
from openpyxl import load_workbook
from timespan import parse_date, parse_date_range
from metadati.values import (
    clean_value,
    clean_metadata_value,
    _date_interval,
    _split_biographical_date_range,
    parse_coordinates,
    parse_source_label,
)


# ---------------------------------------------------------------------------
# XLSX reader
# ---------------------------------------------------------------------------


def _read_sheet_rows(sheet):
    rows = []
    for row in sheet.iter_rows(values_only=True):
        if not row:
            continue
        field = str(row[0]).strip() if len(row) > 0 and row[0] else ""
        value = row[1] if len(row) > 1 else None
        extra = row[2] if len(row) > 2 else None
        rows.append((field, value, extra))
    return rows


def _parse_identifier(field, value_str):
    if field == "ID Sprecher":
        return value_str

    combined = " ".join([x for x in [field, value_str] if x]).replace("\u2013", "-")
    match = re.search(r"Metadaten\s*-\s*([A-Za-z0-9_]+)", combined)
    return match.group(1) if match else None


def _update_birth_place(birth_place, value_str, extra_str):
    metadata = " | ".join(value for value in (value_str, extra_str) if value)
    name_match = re.search(
        r"(?:^|\||\n)\s*Ortsname\s*:\s*([^|\r\n]+)",
        metadata,
        flags=re.IGNORECASE,
    )
    birth_place["name"] = (
        name_match.group(1).strip() if name_match else value_str.splitlines()[0].strip()
    )

    for part in (p.strip() for p in re.split(r"\||\r?\n", metadata) if p.strip()):
        key, separator, detail = part.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().casefold()
        detail = detail.strip()
        if normalized_key in {"land", "region", "kreis"}:
            birth_place["regions"].append(detail)
        elif "koordinat" in normalized_key:
            birth_place["coordinates"] = parse_coordinates(detail)
        elif normalized_key in {"wikidata", "wikidata id"}:
            birth_place["wikidata_id"] = detail


def _parse_person_field(person, birth_place, field, value_str, extra_str):
    if field == "Vorname":
        person["given_name"] = value_str
    elif field in {"ehem. Vorname", "ehemaliger Vorname"}:
        person["previous_given_name"] = value_str
    elif field == "Nachname":
        person["family_name"] = value_str
    elif field in {"ehem. Nachname", "ehemaliger Nachname"}:
        person["previous_family_name"] = value_str
    elif field == "Geschlecht":
        person["gender"] = value_str
    elif field == "Geburtsdatum":
        person["birth_date"] = parse_date(value_str) if value_str else None
        person["birth_date_interval"] = _date_interval(value_str)
    elif field in {"Verfolgtengruppe NS", "Verfolgtengruppe(n) NS"}:
        person["attributes"]["ns_persecution_group"] = value_str
    elif field == "Schulbildung / Abschluss":
        person["education"] = clean_metadata_value(value_str)
    elif field == "Beruf (zum Zeitpunkt der Emigration)":
        person["occupation_at_emigration"] = clean_metadata_value(value_str)
    elif field == "Beruf (zum Zeitpunkt der Quelle)":
        person["occupation_at_source"] = clean_metadata_value(value_str)
    elif field == "Wohnort zum Zeitpunkt der Quelle":
        person["residence_at_source"] = clean_metadata_value(value_str)
    elif field == "Geburtsort":
        _update_birth_place(birth_place, value_str, extra_str)


def _new_interview():
    return {
        "type": None,
        "place": None,
        "date": None,
        "interviewer": None,
        "archive_id": None,
        "url": None,
    }


def _parse_source_field(field, value, value_str, interviews):
    match = re.match(r"Quelle\s+(\d+)\s*[-\u2013\u2014]\s*(.+)", field)
    if not match:
        return

    index = int(match.group(1))
    subfield = match.group(2)
    while len(interviews) < index:
        interviews.append(_new_interview())
    current = interviews[index - 1]

    if subfield == "Typ":
        current["type"] = clean_value(value)
    elif subfield == "Ort":
        current["place"] = clean_value(value)
    elif subfield == "Datum":
        current["date"] = parse_date(value_str) if value_str else None
    elif subfield == "Gesprächspartner/in":
        current["interviewer"] = clean_value(value)
    elif subfield == "Bezeichnung":
        interviewer, archive_id = parse_source_label(value)
        current["interviewer"] = interviewer
        current["archive_id"] = archive_id
    elif subfield == "Handle/URL":
        current["url"] = clean_value(value)
    elif subfield == "ID":
        current["archive_id"] = clean_value(value)


def _parse_person_sheet(rows):
    person = {
        "given_name": None,
        "previous_given_name": None,
        "family_name": None,
        "previous_family_name": None,
        "gender": None,
        "birth_date": None,
        "birth_date_interval": None,
        "education": None,
        "occupation_at_emigration": None,
        "occupation_at_source": None,
        "residence_at_source": None,
        "attributes": {},
    }
    birth_place = {
        "name": None,
        "coordinates": None,
        "wikidata_id": None,
        "regions": [],
    }
    interviews = []
    identifier = None
    in_sources_section = False

    for field, value, extra in rows:
        value_str = clean_value(value)
        extra_str = clean_value(extra)

        if identifier is None:
            identifier = _parse_identifier(field, value_str)

        if field == "QUELLEN":
            in_sources_section = True
            continue
        if field == "MIGRATION":
            in_sources_section = False

        _parse_person_field(person, birth_place, field, value_str, extra_str)

        if in_sources_section or field.startswith("Quelle "):
            _parse_source_field(field, value, value_str, interviews)

    interviews = [
        interview
        for interview in interviews
        if any(
            [
                interview["type"],
                interview["place"],
                interview["date"],
                interview["interviewer"],
                interview["archive_id"],
                interview["url"],
            ]
        )
    ]
    return identifier, person, birth_place, interviews


def _parse_family_sheet(sheet):
    family = []
    for row in sheet.iter_rows(min_row=4, max_col=7, values_only=True):
        if all(cell is None for cell in row):
            continue
        (
            _,
            relation,
            given_name,
            family_name,
            birth_date_raw,
            birth_place,
            notes,
        ) = row
        birth_date_interval, death_date_interval = _split_biographical_date_range(
            birth_date_raw
        )
        birth_date, death_date = (
            parse_date_range(str(birth_date_raw)) if birth_date_raw else (None, None)
        )
        family.append(
            {
                "relation": clean_value(relation),
                "given_name": clean_value(given_name),
                "family_name": clean_value(family_name),
                "birth_date": birth_date,
                "birth_date_interval": birth_date_interval,
                "death_date": death_date,
                "death_date_interval": death_date_interval,
                "birth_place": clean_value(birth_place),
                "notes": clean_value(notes),
            }
        )
    return family


def read_person_record(xlsx_path, sheet_name="Scheda individuale"):
    """Parse a metadati xlsx file into a structured record dict."""
    wb = load_workbook(xlsx_path)
    sheet = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    assert sheet is not None, f"No sheet found in {xlsx_path}"

    identifier, person, birth_place, interviews = _parse_person_sheet(
        _read_sheet_rows(sheet)
    )
    family = _parse_family_sheet(wb["Familie"]) if "Familie" in wb.sheetnames else []

    return {
        "identifier": identifier,
        "person": person,
        "birth_place": birth_place,
        "interviews": interviews,
        "family": family,
    }
