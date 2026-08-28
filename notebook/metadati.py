"""Metadati (person metadata) import logic.

Reads metadati_*.xlsx files and imports person records, relationships,
interviews, and birth places via the Django REST API.
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook

from api_client import api_get, api_post, api_patch, SESSION, BASE_URL
from utils import is_empty
from timespan import parse_date, parse_date_range


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


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_timespan_cache: dict = {}
_person_cache: dict = {}
_relationship_type_cache: dict = {}
_relationship_cache: dict = {}


# ---------------------------------------------------------------------------
# Utility helpers (metadati-specific)
# ---------------------------------------------------------------------------


def clean_label(label):
    label = label.strip().lower()
    label = label.replace("(", "").replace(")", "")
    label = label.replace(".", "")
    label = " ".join(label.split())
    return label


def clean_value(value):
    if not value:
        return None
    value = str(value).strip()
    if is_empty(value):
        return None
    return value


def parse_coordinates(text):
    match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", text)
    if match:
        return {"lat": float(match.group(1)), "lon": float(match.group(2))}
    return None


def parse_name(full_name):
    if not full_name:
        return None, None
    full_name = full_name.strip()
    if "," in full_name:
        parts = full_name.split(",")
        family_name = parts[0].strip()
        given_name = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
        return given_name, family_name
    parts = full_name.split()
    if len(parts) > 1:
        return parts[0], " ".join(parts[1:])
    return full_name, "UNKNOWN"


# ---------------------------------------------------------------------------
# Timespan (metadati-specific: searches API before creating)
# ---------------------------------------------------------------------------


def get_or_create_timespan(start=None, end=None):
    """Get or create a Timespan singleton. Returns id or None."""
    if start is None and end is None:
        return None
    key = (start, end)
    if key in _timespan_cache:
        return _timespan_cache[key]
    existing = api_get("timespans")
    for ts in existing:
        if ts.get("start") == start and ts.get("end") == end:
            _timespan_cache[key] = ts["id"]
            return ts["id"]
    created = api_post("timespans", {"start": start, "end": end})
    _timespan_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# XLSX reader
# ---------------------------------------------------------------------------


def read_person_record(xlsx_path, sheet_name="Scheda individuale"):
    """Parse a metadati xlsx file into a structured record dict."""
    wb = load_workbook(xlsx_path)
    sheet = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    assert sheet is not None, f"No sheet found in {xlsx_path}"

    rows = []
    for row in sheet.iter_rows(values_only=True):
        if not row:
            continue
        field = str(row[0]).strip() if len(row) > 0 and row[0] else ""
        value = row[1] if len(row) > 1 else None
        extra = row[2] if len(row) > 2 else None
        rows.append((field, value, extra))

    record = {
        "identifier": None,
        "person": {
            "given_name": None,
            "previous_given_name": None,
            "family_name": None,
            "previous_family_name": None,
            "gender": None,
            "birth_date": None,
            "attributes": {},
        },
        "birth_place": {
            "name": None,
            "coordinates": None,
            "wikidata_id": None,
            "regions": [],
        },
        "interviews": [],
        "family": [],
    }

    in_sources_section = False

    for field, value, extra in rows:
        field = field.strip() if field else ""
        value_str = clean_value(value)
        extra_str = clean_value(extra)

        # Identifier from "ID Sprecher" field
        if record["identifier"] is None:
            if field == "ID Sprecher":
                record["identifier"] = value_str
            else:
                # Fallback: extract from title row
                combined = " ".join([x for x in [field, value_str] if x]).replace(
                    "\u2013", "-"
                )
                match = re.search(r"Metadaten\s*-\s*([A-Za-z0-9_]+)", combined)
                if match:
                    record["identifier"] = match.group(1)

        # Section markers (optional, for future format compatibility)
        if field == "QUELLEN":
            in_sources_section = True
            continue
        if field == "MIGRATION":
            in_sources_section = False

        # Person fields (parse directly without section markers)
        if field == "Vorname":
            record["person"]["given_name"] = value_str
        elif field == "ehem. Vorname" or field == "ehemaliger Vorname":
            record["person"]["previous_given_name"] = value_str
        elif field == "Nachname":
            record["person"]["family_name"] = value_str
        elif field == "ehem. Nachname" or field == "ehemaliger Nachname":
            record["person"]["previous_family_name"] = value_str
        elif field == "Geschlecht":
            record["person"]["gender"] = value_str
        elif field == "Geburtsdatum":
            record["person"]["birth_date"] = (
                parse_date(value_str) if value_str else None
            )
        elif field == "Verfolgtengruppe NS" or field == "Verfolgtengruppe(n) NS":
            record["person"]["attributes"]["ns_persecution_group"] = value_str
        elif field == "Geburtsort":
            record["birth_place"]["name"] = value_str
            if extra_str:
                for part in (p.strip() for p in extra_str.split("|") if p.strip()):
                    if part.startswith("Land:"):
                        record["birth_place"]["regions"].append(
                            part.split(":", 1)[1].strip()
                        )
                    elif part.startswith("Region:"):
                        record["birth_place"]["regions"].append(
                            part.split(":", 1)[1].strip()
                        )
                    elif part.startswith("Kreis:"):
                        record["birth_place"]["regions"].append(
                            part.split(":", 1)[1].strip()
                        )
                    elif part.startswith("Koordinaten:"):
                        record["birth_place"]["coordinates"] = parse_coordinates(
                            part
                        )
                    elif part.startswith("Wikidata:"):
                        record["birth_place"]["wikidata_id"] = part.split(":", 1)[
                            1
                        ].strip()

        # Interviews/Sources
        if in_sources_section or field.startswith("Quelle "):
            m = re.match(r"Quelle (\d+)\s*\u2013\s*(.+)", field)
            if not m:
                continue
            index = int(m.group(1))
            subfield = m.group(2)
            while len(record["interviews"]) < index:
                record["interviews"].append(
                    {
                        "type": None,
                        "place": None,
                        "date": None,
                        "interviewer": None,
                        "archive_id": None,
                    }
                )
            current = record["interviews"][index - 1]
            if subfield == "Typ":
                current["type"] = clean_value(value)
            elif subfield == "Ort":
                current["place"] = clean_value(value)
            elif subfield == "Datum":
                current["date"] = parse_date(value_str) if value_str else None
            elif subfield == "Gesprächspartner/in":
                current["interviewer"] = clean_value(value)
            elif subfield == "ID":
                current["archive_id"] = clean_value(value)

    record["interviews"] = [
        i
        for i in record["interviews"]
        if any([i["type"], i["place"], i["date"], i["interviewer"], i["archive_id"]])
    ]

    # Family sheet
    if "Familie" in wb.sheetnames:
        sheet_fam = wb["Familie"]
        for idx, row in enumerate(sheet_fam.iter_rows(values_only=True)):
            if idx <= 1:
                continue
            if not row or all(cell is None for cell in row):
                continue
            cells = list(row)[:7]
            while len(cells) < 7:
                cells.append(None)
            (
                _,
                relation,
                given_name,
                family_name,
                birth_date_raw,
                birth_place,
                notes,
            ) = cells
            birth_date, death_date = (
                parse_date_range(str(birth_date_raw))
                if birth_date_raw
                else (None, None)
            )
            record["family"].append(
                {
                    "relation": clean_value(relation),
                    "given_name": clean_value(given_name),
                    "family_name": clean_value(family_name),
                    "birth_date": birth_date,
                    "death_date": death_date,
                    "birth_place": clean_value(birth_place),
                    "notes": clean_value(notes),
                }
            )

    return record


# ---------------------------------------------------------------------------
# Location (birth place)
# ---------------------------------------------------------------------------


def get_or_create_region_hierarchy(region_list):
    """Create or retrieve a chain of LocationRegion objects via the API.
    Returns the innermost region's id, or None."""
    if not region_list:
        return None

    parent_id = None
    for name in region_list:
        if is_empty(name):
            continue

        existing = api_get("regions", params={"search": name})
        match = next((r for r in existing if r["name"] == name), None)

        if match:
            region_id = match["id"]
            if parent_id and match.get("part_of") != parent_id:
                api_patch("regions", region_id, {"part_of": parent_id})
        else:
            payload = {"name": name}
            if parent_id:
                payload["part_of"] = parent_id
            created = api_post("regions", payload)
            region_id = created["id"]

        parent_id = region_id

    return parent_id


def get_or_create_location(bp):
    """Create or retrieve a LocationPoint from a birth_place dict."""
    if is_empty(bp.get("name")):
        return None

    existing = api_get("locations", params={"search": bp["name"]})
    match = next((loc for loc in existing if loc["current_name"] == bp["name"]), None)

    if match:
        loc_id = match["id"]
        if not match.get("region"):
            region_id = get_or_create_region_hierarchy(bp.get("regions"))
            if region_id:
                SESSION.patch(
                    f"{BASE_URL}/locations/{loc_id}/",
                    json={"region": region_id},
                )
        return loc_id

    payload = {"current_name": bp["name"]}
    if bp.get("wikidata_id"):
        payload["wikidata_id"] = bp["wikidata_id"]
    if bp.get("coordinates"):
        payload["latitude"] = bp["coordinates"]["lat"]
        payload["longitude"] = bp["coordinates"]["lon"]

    region_id = get_or_create_region_hierarchy(bp.get("regions"))
    if region_id:
        payload["region"] = region_id

    created = api_post("locations", payload)
    return created["id"]


# ---------------------------------------------------------------------------
# Person matching
# ---------------------------------------------------------------------------


def _maybe_update_lifespan(person_id, data):
    """Update a person's lifespan if new date data is available."""
    birth = data.get("birth_date")
    death = data.get("death_date")
    if not birth and not death:
        return
    person = SESSION.get(f"{BASE_URL}/persons/{person_id}/").json()
    existing_ts_id = person.get("lifespan")
    cur_start = None
    cur_end = None
    if existing_ts_id:
        ts = SESSION.get(f"{BASE_URL}/timespans/{existing_ts_id}/").json()
        cur_start = ts.get("start")
        cur_end = ts.get("end")
        new_start = birth or cur_start
        new_end = death or cur_end
        if new_start == cur_start and new_end == cur_end:
            return  # no change
    else:
        new_start = birth
        new_end = death
    new_ts_id = get_or_create_timespan(start=new_start, end=new_end)
    if new_ts_id and new_ts_id != existing_ts_id:
        SESSION.patch(f"{BASE_URL}/persons/{person_id}/", json={"lifespan": new_ts_id})
        # Remove old timespan from cache and delete if orphaned
        if existing_ts_id:
            old_key = (cur_start, cur_end)
            _timespan_cache.pop(old_key, None)
            # Delete orphaned timespan (no other person references it after update)
            referencing = api_get("persons", params={"search": ""})
            still_used = any(p.get("lifespan") == existing_ts_id for p in referencing)
            if not still_used:
                SESSION.delete(f"{BASE_URL}/timespans/{existing_ts_id}/")


def get_or_create_person(data, identifier=None):
    """Create or match a Person via the API. Returns person id or None."""
    given_name = data.get("given_name")
    family_name = data.get("family_name")

    if is_empty(given_name) and is_empty(family_name):
        return None

    # Match on identifier
    if identifier:
        existing = api_get("persons", params={"search": identifier})
        match = next((p for p in existing if p.get("identifier") == identifier), None)
        if match:
            key = (match["given_name"].lower(), match["family_name"].lower())
            _person_cache[key] = match["id"]
            _maybe_update_lifespan(match["id"], data)
            # Update previous names if available and not already set
            patch = {}
            if data.get("previous_given_name") and not match.get("previous_given_name"):
                patch["previous_given_name"] = data["previous_given_name"]
            if data.get("previous_family_name") and not match.get(
                "previous_family_name"
            ):
                patch["previous_family_name"] = data["previous_family_name"]
            if patch:
                api_patch("persons", match["id"], patch)
            return match["id"]
        payload = {
            "identifier": identifier,
            "given_name": given_name or "",
            "family_name": family_name or "",
        }
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
                return p["id"]

    payload = {
        "given_name": given_name or "",
        "family_name": family_name or "",
    }
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


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


def _clean_interview_type(raw):
    """Remove 'Interview' prefix and clean Excel errors from type field."""
    if not raw or raw.startswith("#"):
        return ""
    cleaned = re.sub(r"^Interview\s*", "", raw, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip("()")
    return cleaned


def create_interview(person_id, data):
    """Create an Interview via the API."""
    if is_empty(data.get("archive_id")):
        return None

    archive_id = data["archive_id"]

    existing = api_get("interviews", params={"search": archive_id})
    match = next((i for i in existing if i["archive_id"] == archive_id), None)
    if match:
        return match["id"]

    interviewer_id = None
    if not is_empty(data.get("interviewer")):
        given, family = parse_name(data["interviewer"])
        interviewer_id = get_or_create_person(
            {
                "given_name": given,
                "family_name": family,
            }
        )

    payload = {
        "archive_id": archive_id,
        "interviewee": person_id,
        "interview_type": _clean_interview_type(data.get("type")),
        "date": data.get("date"),
        "place": data.get("place") or "",
    }
    if interviewer_id:
        payload["interviewer"] = interviewer_id

    created = api_post("interviews", payload)
    return created["id"]


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------


def get_or_create_relationship_type(label):
    """Get or create a RelationshipType via the API."""
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


def create_relationship(main_person_id, data, fallback_family_name):
    """Create a Relationship via the API."""
    if is_empty(data.get("relation")):
        return None

    given_name = data.get("given_name")
    family_name = data.get("family_name")
    if is_empty(family_name):
        family_name = fallback_family_name

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


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------


def import_record(record):
    """Import a full person record (parsed JSON) via API calls."""
    person_id = get_or_create_person(
        record["person"],
        identifier=record.get("identifier"),
    )
    if not person_id:
        print("Skipped: invalid person")
        return None

    # Birth place
    location_id = get_or_create_location(record.get("birth_place", {}))
    if location_id:
        SESSION.patch(
            f"{BASE_URL}/persons/{person_id}/",
            json={"birth_place": location_id},
        )

    # Interviews
    for interview_data in record.get("interviews", []):
        create_interview(person_id, interview_data)

    # Family / relationships
    person_data = SESSION.get(f"{BASE_URL}/persons/{person_id}/").json()
    main_family_name = person_data.get("family_name", "")
    for family_data in record.get("family", []):
        create_relationship(person_id, family_data, main_family_name)

    return person_id


def import_from_xlsx(xlsx_path):
    """Parse an xlsx file and import the person record via the API."""
    record = read_person_record(xlsx_path)
    person_id = import_record(record)
    if person_id:
        print(f"\u2705 Imported: {xlsx_path}")
    else:
        print(f"\u26a0\ufe0f Skipped: {xlsx_path}")
    return person_id


def import_all_metadati(directory=None):
    """Find and import all metadati_*.xlsx files from the data directory."""
    if directory is None:
        directory = Path(__file__).resolve().parent.parent / "data" / "schede mappatura"
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
