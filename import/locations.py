import logging
import json
import os
import time
import math
import openpyxl
import requests
import regex as re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from utils import extract_id_from_url, is_empty


logger = logging.getLogger(__name__)

LOCATION_TAXONOMY_SYNONYMS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "location_taxonomy_synonyms.json"
)
LOCATIONS_WORKBOOK_PATH = Path(__file__).resolve().parent / "locations.xlsx"


GEONAMES_USERNAME = "mapto"

domains = ["geonames.org", "wikidata.org"]


def taxonomy_label_key(value):
    """Normalize a location label for taxonomy synonym matching."""
    value = re.sub(r"[-_]+", " ", str(value or "").casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


@dataclass(frozen=True)
class LocationTaxonomySynonyms:
    """Reviewed location-to-GO synonyms, with keys normalized for matching.

    Query overrides are the exception: they match exact source labels.
    The mappings are read-only; copy them before changing anything.
    """

    aliases: Mapping[str, str]
    canonical_parents: Mapping[str, str]
    excluded_terms: frozenset[str]
    reviewed_unmapped_keys: frozenset[str]
    reviewed_unmapped_labels: frozenset[str]
    query_overrides: Mapping[str, str]

    def alias_for(self, value) -> str:
        """Return the reviewed canonical GO label, or the value when unreviewed."""
        return self.aliases.get(taxonomy_label_key(value), value)

    def canonical_parent_for(self, value) -> str | None:
        """Return the reviewed GO parent hint for a supplemental location."""
        return self.canonical_parents.get(taxonomy_label_key(value))

    def query_override_for(self, value) -> str | None:
        """Return the reviewed geocoder query for an exact source label, if any."""
        return self.query_overrides.get(value)

    def is_reviewed_unmapped(self, value) -> bool:
        """Return whether the reviewed table lists the label as not a location."""
        key = taxonomy_label_key(value)
        raw_value = str(value or "").strip().casefold()
        return bool(
            raw_value in self.reviewed_unmapped_labels
            or (key and key in self.reviewed_unmapped_keys)
        )

    def is_excluded(self, value) -> bool:
        """Return whether a reviewed location is intentionally left unmapped."""
        key = taxonomy_label_key(value)
        return bool(
            self.is_reviewed_unmapped(value)
            or any(term in key for term in self.excluded_terms)
        )


@lru_cache(maxsize=1)
def location_taxonomy_synonyms() -> LocationTaxonomySynonyms:
    """Load the shared reviewed location-to-GO synonym table."""
    data = json.loads(LOCATION_TAXONOMY_SYNONYMS_PATH.read_text(encoding="utf-8"))
    reviewed_unmapped = data.get("reviewed_unmapped", [])
    return LocationTaxonomySynonyms(
        aliases=MappingProxyType(
            {
                taxonomy_label_key(source): target
                for source, target in data.get("aliases", {}).items()
            }
        ),
        canonical_parents=MappingProxyType(
            {
                taxonomy_label_key(source): target
                for source, target in data.get("canonical_parents", {}).items()
            }
        ),
        excluded_terms=frozenset(
            taxonomy_label_key(value) for value in data.get("excluded_contains", [])
        ),
        reviewed_unmapped_keys=frozenset(
            taxonomy_label_key(label) for label in reviewed_unmapped
        ),
        reviewed_unmapped_labels=frozenset(
            str(label).strip().casefold() for label in reviewed_unmapped
        ),
        query_overrides=MappingProxyType(dict(data.get("query_overrides", {}))),
    )


def taxonomy_alias(value):
    """Return the reviewed canonical GO label for a source synonym."""
    return location_taxonomy_synonyms().alias_for(value)


def taxonomy_match_excluded(value):
    """Return whether a reviewed location is intentionally left unmapped."""
    return location_taxonomy_synonyms().is_excluded(value)


def taxonomy_reviewed_unmapped(value):
    """Return whether the reviewed table lists a source label as not a location."""
    return location_taxonomy_synonyms().is_reviewed_unmapped(value)


def taxonomy_location_parent(value):
    """Return the reviewed GO parent hint for a supplemental location concept."""
    return location_taxonomy_synonyms().canonical_parent_for(value)


def taxonomy_query_override(value):
    """Return the reviewed geocoder query for an exact source label, if any."""
    return location_taxonomy_synonyms().query_override_for(value)


def canonical_location_name(value, locations_db=None):
    """Map a source location spelling to one workbook entity when possible."""
    cleaned = str(value or "").strip()
    if not cleaned or taxonomy_reviewed_unmapped(cleaned) or cleaned.startswith("http"):
        return None
    if locations_db is None:
        return cleaned

    candidates = []
    for seed in (taxonomy_alias(cleaned), cleaned):
        candidate = seed
        while candidate:
            if candidate not in candidates:
                candidates.append(candidate)
            if not re.search(r"\([^()]*\)", candidate):
                break
            candidate = re.sub(r"\s*\([^()]*\)", "", candidate).strip()

    for candidate in candidates:
        key = normalize_location(candidate)
        if key in locations_db:
            return locations_db[key].get("name", candidate)

    candidate_keys = {normalize_location(candidate) for candidate in candidates}
    for record in locations_db.values():
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        record_keys = {
            normalize_location(name),
            normalize_location(taxonomy_alias(name)),
        }
        if candidate_keys & record_keys:
            return name

    source_tokens = set(normalize_location(cleaned).split())
    matching = []
    for record in locations_db.values():
        name = record.get("name", "")
        tokens = set(normalize_location(name).split())
        if tokens and tokens <= source_tokens:
            matching.append((len(tokens), name))
    if matching:
        return max(matching)[1]
    return cleaned


def _coordinate_pair(entry: dict) -> tuple[float, float] | None:
    """Return a finite ``(latitude, longitude)`` pair when both values exist."""
    try:
        latitude = float(entry.get("lat"))
        longitude = float(entry.get("long"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    return latitude, longitude


def extract_geonames_id(value) -> str | None:
    """Return the numeric GeoNames ID from an ID or GeoNames URL.

    GeoNames entity URLs end with a slug, so taking the final URL component
    would produce values such as ``republic-of-france.html`` instead of the
    API-safe ID ``3017382``.
    """
    raw_value = str(value or "").strip()
    if not raw_value or raw_value in ("nan", "None"):
        return None
    raw_value = raw_value.removesuffix(".0")
    if raw_value.isdigit():
        return raw_value
    match = re.search(r"geonames\.org/(\d+)(?:/|$)", raw_value, flags=re.IGNORECASE)
    return match.group(1) if match else None


def resolve_location_coordinates(entry: dict) -> tuple[float, float] | None:
    """Resolve coordinates table-first, then source IDs, then by place name.

    Successful fallback values are written back to *entry* so
    :func:`save_locations_db` can persist them to ``locations.xlsx``.
    """
    coordinates = _coordinate_pair(entry)
    if coordinates is not None:
        entry["lat"], entry["long"] = coordinates
        return coordinates

    for url_key, resolver in (
        ("geonames_url", extract_geonames_coordinates),
        ("wikidata_url", extract_wikidata_coordinates),
    ):
        url = entry.get(url_key)
        if not url:
            continue
        try:
            coordinates = resolver(url)
        except requests.RequestException as exc:
            logger.warning(
                "Coordinate lookup failed for %s via %s (%s): %s",
                entry.get("name", "<unnamed location>"),
                url_key,
                url,
                exc,
            )
            continue
        except Exception:
            logger.exception(
                "Unexpected coordinate lookup failure for %s via %s (%s)",
                entry.get("name", "<unnamed location>"),
                url_key,
                url,
            )
            continue
        if coordinates is None:
            logger.warning(
                "No coordinates returned for %s via %s (%s)",
                entry.get("name", "<unnamed location>"),
                url_key,
                url,
            )
            continue
        coordinates = _coordinate_pair(
            {"lat": coordinates.get("lat"), "long": coordinates.get("long")}
        )
        if coordinates is not None:
            entry["lat"], entry["long"] = coordinates
            return coordinates

    has_source_id = any(
        not is_empty(entry.get(field))
        for field in (
            "geonames_id",
            "wikidata_id",
            "geonames_url",
            "wikidata_url",
        )
    )
    if not has_source_id and not is_empty(entry.get("name")):
        name = str(entry["name"]).strip()
        try:
            coordinates = query_geocoder(name)
        except Exception:
            logger.exception("Name geocoder failed for %s", name)
            coordinates = None
        if coordinates is not None:
            coordinates = _coordinate_pair(coordinates)
            if coordinates is not None:
                entry["lat"], entry["long"] = coordinates
                return coordinates
        logger.warning("Name geocoder returned no usable coordinates for %s", name)

    logger.warning(
        "No usable coordinate source for %s",
        entry.get("name", "<unnamed location>"),
    )
    return None


def extract_geonames_coordinates(url: str) -> dict | None:
    """
    Extract coordinates from a GeoNames URL.

    Handles two URL formats:
    - Entity URL (e.g. https://www.geonames.org/6550600/finsterwalde.html)
      → fetches via GeoNames API using the numeric ID
    - Map URL (e.g. https://www.geonames.org/maps/google_52.4863_13.3602.html)
      → extracts coordinates directly from the URL

    Returns dict with 'lat' and 'long', or None if not found.
    """
    # Map URL with embedded coordinates
    map_match = re.search(r"geonames\.org/maps/google_([-\d.]+)_([-\d.]+)", url)
    if map_match:
        try:
            return {"lat": float(map_match.group(1)), "long": float(map_match.group(2))}
        except ValueError as exc:
            logger.warning(
                "Invalid coordinates embedded in GeoNames URL %s: %s", url, exc
            )
            return None

    # Entity URL with numeric ID
    match = re.search(r"geonames\.org/(\d+)", url)
    if not match:
        logger.warning("GeoNames URL has no entity ID: %s", url)
        return None

    geoname_id = match.group(1)

    try:
        response = requests.get(
            "https://api.geonames.org/getJSON",
            params={"geonameId": geoname_id, "username": GEONAMES_USERNAME},
            headers={"User-Agent": "coord-extractor/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        coordinates = {"lat": float(data["lat"]), "long": float(data["lng"])}
        if _coordinate_pair(coordinates) is not None:
            return coordinates
    except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning(
            "GeoNames API lookup failed for %s (%s): %s", url, geoname_id, exc
        )

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "coord-extractor/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        match = re.search(
            r'"@type"\s*:\s*"GeoCoordinates".*?'
            r'"latitude"\s*:\s*(-?[\d.]+).*?'
            r'"longitude"\s*:\s*(-?[\d.]+)',
            response.text,
            flags=re.DOTALL,
        )
        if match:
            return {"lat": float(match.group(1)), "long": float(match.group(2))}
    except (ValueError, requests.RequestException) as exc:
        logger.warning("GeoNames page lookup failed for %s: %s", url, exc)
    return None


def extract_wikidata_coordinates(url: str) -> dict | None:
    """
    Extract coordinates from a Wikidata entity URL.
    e.g. https://www.wikidata.org/wiki/Q64

    Fetches the entity via the Wikidata API and reads property P625 (coordinate location).
    Returns dict with 'lat' and 'lng', or None if not found.
    """
    match = re.search(r"/wiki/(Q\d+)", url)
    if not match:
        logger.warning("Wikidata URL has no entity ID: %s", url)
        return None

    qid = match.group(1)

    response = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims",
            "format": "json",
        },
        headers={"User-Agent": "coord-extractor/1.0"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    try:
        claims = data["entities"][qid]["claims"]
        p625 = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
        return {"lat": p625["latitude"], "long": p625["longitude"]}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Wikidata entity %s has no usable coordinates: %s", qid, exc)
        return None


# Using https://github.com/mapto/whereami with container port exposed at port 3000
GEOCODER_URL = "http://localhost:3000/at"


def query_geocoder(name):
    """Resolve *name* through the whereami multi-provider geocoder service."""
    try:
        time.sleep(1.1)
        resp = requests.get(GEOCODER_URL, params={"name": name}, timeout=5)
        resp.raise_for_status()
        parts = resp.text.strip().split(",")
        if len(parts) >= 2:
            return {"lat": float(parts[0]), "long": float(parts[1])}
    except Exception as exc:
        logger.warning("Geocoder lookup failed for %s: %s", name, exc)
    return None


# --- Bag-of-words & super-region logic ---


def tokenize_location(name):
    """Tokenize a location name into a set of lowercase words, stripping punctuation."""
    name = str(name).strip().lower()
    name = re.sub(r"[^\w\s]", "", name)
    return set(name.split()) - {""}


def compute_super_regions(locations):
    """Given a dict of {name: bag_of_words}, return {name: super_region_name}.

    A location A is the super-region of B if A's bag is a strict subset of B's bag.
    Among all subsets, pick the one with the most words (closest ancestor).
    """
    items = [(name, bow) for name, bow in locations.items() if bow]
    result = {}
    for name, bow in items:
        best_parent = None
        best_len = 0
        for other_name, other_bow in items:
            if other_name == name:
                continue
            if other_bow < bow and len(other_bow) > best_len:
                best_parent = other_name
                best_len = len(other_bow)
        result[name] = best_parent or ""
    return result


def enrich_locations_xlsx(xlsx_path):
    """Add bag_of_words and super_region columns to an existing locations.xlsx.

    Only adds information; never removes existing data.
    """
    import openpyxl as _xl

    wb = _xl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws is not None

    # Read header row
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

    # Ensure new columns exist
    bow_col = None
    sr_col = None
    if "bag_of_words" in headers:
        bow_col = headers.index("bag_of_words") + 1
    if "super_region" in headers:
        sr_col = headers.index("super_region") + 1

    if bow_col is None:
        bow_col = 2  # insert after column 1
        ws.insert_cols(2)
        ws.cell(1, 2).value = "bag_of_words"  # type: ignore[reportAttributeAccessIssue]
        # Shift sr_col if it existed
        if sr_col is not None:
            sr_col += 1
        # Re-read headers after insert
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

    if sr_col is None:
        sr_col = bow_col + 1
        ws.insert_cols(sr_col)
        ws.cell(1, sr_col).value = "super_region"  # type: ignore[reportAttributeAccessIssue]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

    # Build bag-of-words for all locations
    loc_bows = {}  # row -> (name, bow_set)
    for r in range(2, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not name:
            continue
        bow = tokenize_location(name)
        ws.cell(r, bow_col).value = " ".join(sorted(bow))  # type: ignore[reportAttributeAccessIssue]
        loc_bows[r] = (str(name).strip(), bow)

    # Compute super-regions
    name_to_bow = {name: bow for _, (name, bow) in loc_bows.items()}
    super_regions = compute_super_regions(name_to_bow)

    # Write super-region column (only if currently empty)
    for r, (name, _) in loc_bows.items():
        existing = ws.cell(r, sr_col).value
        if not existing or str(existing).strip() in ("", "nan"):
            sr = super_regions.get(name, "")
            if sr:
                ws.cell(r, sr_col).value = sr

    wb.save(xlsx_path)


# ---------------------------------------------------------------------------
# Locations database (locations.xlsx) — load, save, upsert
# ---------------------------------------------------------------------------

# Column layout (1-indexed):
#   1: location, 2: bag_of_words, 3: super_region,
#   4: lat, 5: long, 6: label,
#   7: www.geonames.org, 8: www.wikidata.org, 9+: other URLs

_locations_db = {}  # normalize_location(name) -> {name, lat, long, ...}


def normalize_location(name):
    """Normalize a location name for matching: lowercase, no punctuation, sorted words."""
    name = str(name).strip().casefold()
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(sorted(name.split()))


def load_locations_db(xlsx_path=None, *, enrich_coordinates=True, save_enriched=True):
    """Load locations.xlsx and optionally backfill missing coordinates.

    Coordinates already present in the workbook always win. Missing pairs are
    resolved from GeoNames first and Wikidata second, then persisted back to
    the same workbook when ``save_enriched`` is true.
    """
    if xlsx_path is None:
        xlsx_path = LOCATIONS_WORKBOOK_PATH
    if not os.path.exists(xlsx_path):
        logger.warning("locations.xlsx not found at %s, starting fresh", xlsx_path)
        return _locations_db
    _locations_db.clear()
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws is not None
    headers = {
        str(ws.cell(1, column).value or "").strip(): column
        for column in range(1, ws.max_column + 1)
    }

    def cell(row, field, default=""):
        column = headers.get(field)
        return ws.cell(row, column).value if column else default

    def extra_urls_after_geonames(row):
        """Collect every populated workbook column after the GeoNames column."""
        geonames_column = headers.get("www.geonames.org")
        if geonames_column is None:
            return {}
        extra_urls = {}
        for column in range(geonames_column + 1, ws.max_column + 1):
            header = str(ws.cell(1, column).value or "").strip()
            value = str(ws.cell(row, column).value or "").strip()
            if header and value and value.lower() not in {"nan", "none"}:
                extra_urls[header] = value
        return extra_urls

    for r in range(2, ws.max_row + 1):
        name = cell(r, "location")
        if not name:
            continue
        key = normalize_location(name)
        wikidata_url = str(cell(r, "www.wikidata.org") or "").strip()
        geonames_url = str(cell(r, "www.geonames.org") or "").strip()
        _locations_db[key] = {
            "name": str(name).strip(),
            "lat": cell(r, "lat"),
            "long": cell(r, "long"),
            "label": str(cell(r, "label") or "").strip(),
            "wider_region": str(cell(r, "wider_region") or "").strip(),
            "coordinate_source": str(cell(r, "coordinate_source") or "").strip(),
            "wikidata_id": extract_id_from_url(wikidata_url),
            "geonames_id": extract_geonames_id(geonames_url),
            "wikidata_url": wikidata_url
            if wikidata_url and wikidata_url != "nan"
            else "",
            "geonames_url": geonames_url
            if geonames_url and geonames_url != "nan"
            else "",
            "extra_url": extra_urls_after_geonames(r),
        }
    if enrich_coordinates:
        changed = False
        for entry in _locations_db.values():
            before = _coordinate_pair(entry)
            # Coordinates in the workbook are the trusted local cache. Do not
            # query external providers when both cached values are present.
            after = (
                before if before is not None else resolve_location_coordinates(entry)
            )
            if after is not None and after != before:
                changed = True
        if changed and save_enriched:
            save_locations_db(xlsx_path)
    print(f"  Loaded {len(_locations_db)} locations from locations.xlsx")
    return _locations_db


def _extra_url_mapping(value):
    """Normalize extra_url to a mapping of workbook headers to URL values."""
    if isinstance(value, dict):
        return {
            str(header).strip(): str(url).strip()
            for header, url in value.items()
            if str(header).strip() and not is_empty(url)
        }
    if isinstance(value, (list, tuple)):
        return {
            f"extra_url_{index + 1}": str(url).strip()
            for index, url in enumerate(value)
            if not is_empty(url)
        }
    if not is_empty(value):
        # Preserve legacy scalar callers without coupling it to a particular host.
        return {"extra_url": str(value).strip()}
    return {}


def save_locations_db(xlsx_path=None):
    """Save _locations_db back to locations.xlsx, merging with existing data."""
    if xlsx_path is None:
        xlsx_path = LOCATIONS_WORKBOOK_PATH
    HEADERS = [
        "location",
        "bag_of_words",
        "super_region",
        "wider_region",
        "coordinate_source",
        "lat",
        "long",
        "label",
        "www.geonames.org",
        "www.wikidata.org",
    ]
    if os.path.exists(xlsx_path):
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        assert ws is not None
        headers = {
            str(ws.cell(1, column).value or "").strip(): column
            for column in range(1, ws.max_column + 1)
        }
        fields = {
            "location": "name",
            "lat": "lat",
            "long": "long",
            "label": "label",
            "wider_region": "wider_region",
            "coordinate_source": "coordinate_source",
            "www.geonames.org": "geonames_url",
            "www.wikidata.org": "wikidata_url",
        }
        existing_rows = {}
        for r in range(2, ws.max_row + 1):
            name_column = headers.get("location")
            name = ws.cell(r, name_column).value if name_column else None
            if name:
                existing_rows[normalize_location(name)] = r
        added = 0
        for key in sorted(_locations_db.keys()):
            loc = _locations_db[key]
            if key in existing_rows:
                row_num = existing_rows[key]
                for header, field in fields.items():
                    column = headers.get(header)
                    if column is None or header == "location":
                        continue
                    if is_empty(ws.cell(row_num, column).value):
                        new_val = loc.get(field)
                        if not is_empty(new_val):
                            ws.cell(row_num, column).value = new_val
                extra_urls = _extra_url_mapping(loc.get("extra_url"))
                for header, url in extra_urls.items():
                    column = headers.get(header)
                    if column is None:
                        column = ws.max_column + 1
                        ws.cell(1, column).value = header
                        headers[header] = column
                    if is_empty(ws.cell(row_num, column).value) and not is_empty(url):
                        ws.cell(row_num, column).value = url
            else:
                values = [""] * ws.max_column
                for header, field in fields.items():
                    column = headers.get(header)
                    if column is not None:
                        values[column - 1] = loc.get(field, "") or ""
                for header, url in _extra_url_mapping(loc.get("extra_url")).items():
                    column = headers.get(header)
                    if column is None:
                        column = ws.max_column + 1
                        ws.cell(1, column).value = header
                        headers[header] = column
                        values.append("")
                    while len(values) < column:
                        values.append("")
                    values[column - 1] = url
                ws.append(values)
                added += 1
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        extra_headers = sorted(
            {
                header
                for location in _locations_db.values()
                for header in _extra_url_mapping(location.get("extra_url"))
                if header not in HEADERS
            }
        )
        output_headers = HEADERS + extra_headers
        ws.append(output_headers)
        added = 0
        for key in sorted(_locations_db.keys()):
            loc = _locations_db[key]
            values = {
                "location": loc["name"],
                "lat": loc.get("lat") or "",
                "long": loc.get("long") or "",
                "label": loc.get("label", ""),
                "wider_region": loc.get("wider_region", ""),
                "coordinate_source": loc.get("coordinate_source", ""),
                "www.geonames.org": loc.get("geonames_url", ""),
                "www.wikidata.org": loc.get("wikidata_url", ""),
            }
            values.update(_extra_url_mapping(loc.get("extra_url")))
            ws.append([values.get(header, "") for header in output_headers])
            added += 1
    wb.save(xlsx_path)
    print(
        f"  Saved locations.xlsx: {added} new rows added, {len(_locations_db)} total in db"
    )


def upsert_location_db(name, wikidata_qid=None, geonames_id=None):
    """Add location to the database if not already present."""
    if not name or str(name).strip() in ("", "nan"):
        return
    name = str(name).strip()
    key = normalize_location(name)
    if key in _locations_db:
        if (
            wikidata_qid
            and wikidata_qid not in ("", "nan")
            and not _locations_db[key].get("wikidata_id")
        ):
            _locations_db[key]["wikidata_id"] = wikidata_qid
            _locations_db[key]["wikidata_url"] = (
                f"https://www.wikidata.org/wiki/{wikidata_qid}"
            )
        if (
            geonames_id
            and geonames_id not in ("", "nan")
            and not _locations_db[key].get("geonames_id")
        ):
            _locations_db[key]["geonames_id"] = geonames_id
            _locations_db[key]["geonames_url"] = (
                f"https://www.geonames.org/{geonames_id}"
            )
        return
    _locations_db[key] = {
        "name": name,
        "lat": None,
        "long": None,
        "label": "",
        "wikidata_id": wikidata_qid
        if wikidata_qid and wikidata_qid not in ("", "nan")
        else "",
        "geonames_id": geonames_id
        if geonames_id and geonames_id not in ("", "nan")
        else "",
        "wikidata_url": f"https://www.wikidata.org/wiki/{wikidata_qid}"
        if wikidata_qid and wikidata_qid not in ("", "nan")
        else "",
        "geonames_url": f"https://www.geonames.org/{geonames_id}"
        if geonames_id and geonames_id not in ("", "nan")
        else "",
        "extra_url": {},
    }


# ---------------------------------------------------------------------------
# Location API operations (get-or-create, region linking)
# ---------------------------------------------------------------------------

_location_cache = {}


def _prepare_location_metadata(
    name,
    wikidata_qid=None,
    geonames_id=None,
    *,
    locations_db=None,
    normalize_fn=None,
):
    """Normalize source values and resolve cached/source location metadata."""
    name = str(name).strip()
    key = (normalize_fn or normalize_location)(name)
    db_entry = dict((locations_db or {}).get(key, {}))
    db_entry.setdefault("name", name)
    if wikidata_qid and not db_entry.get("wikidata_url"):
        db_entry["wikidata_url"] = f"https://www.wikidata.org/wiki/{wikidata_qid}"
    if geonames_id and not db_entry.get("geonames_url"):
        db_entry["geonames_url"] = f"https://www.geonames.org/{geonames_id}"

    coordinates = _coordinate_pair(db_entry)
    if coordinates is None:
        coordinates = resolve_location_coordinates(db_entry)
    return {
        "name": name,
        "key": key,
        "coordinates": coordinates,
        "wikidata_id": db_entry.get("wikidata_id")
        or (wikidata_qid if wikidata_qid and wikidata_qid not in ("", "nan") else None),
        "geonames_id": (
            extract_geonames_id(db_entry.get("geonames_id"))
            or extract_geonames_id(db_entry.get("geonames_url"))
            or extract_geonames_id(geonames_id)
        ),
    }


def _find_location_match(existing, key, normalize_fn):
    """Find an existing API location with the same normalized name."""
    return next(
        (
            location
            for location in existing
            if normalize_fn(location["current_name"]) == key
        ),
        None,
    )


def _find_concept_location(api_get, concept_id, exclude_id=None):
    """Find the location already owning a unique taxonomy concept, if any."""
    if not concept_id:
        return None
    return next(
        (
            location
            for location in api_get("locations")
            if location.get("concept") == concept_id
            and location.get("id") != exclude_id
        ),
        None,
    )


def _reconcile_concept_owner(api_get, api_patch, match, linked, concept_id, key, norm):
    """Keep the exact canonical name as the owner of a unique concept."""
    if linked is None:
        return match
    if match is not None and norm(match["current_name"]) == key:
        if linked["id"] != match["id"]:
            api_patch("locations", linked["id"], {"concept": None})
        api_patch("locations", match["id"], {"concept": concept_id})
        return match
    return linked


def _existing_location_updates(metadata, match, concept_id):
    """Build only missing metadata updates for an existing API location."""
    updates = {}
    if metadata["coordinates"] is not None and not match.get("location"):
        updates["latitude"], updates["longitude"] = metadata["coordinates"]
    if metadata["wikidata_id"] and not match.get("wikidata_id"):
        updates["wikidata_id"] = metadata["wikidata_id"]
    if metadata["geonames_id"] and not match.get("geonames_id"):
        updates["geonames_id"] = metadata["geonames_id"]
    if concept_id and not match.get("concept"):
        updates["concept"] = concept_id
    return updates


def _new_location_payload(metadata, concept_id):
    """Build the API payload for a new location point."""
    payload: dict[str, Any] = {"current_name": metadata["name"]}
    if metadata["coordinates"] is not None:
        payload["latitude"], payload["longitude"] = metadata["coordinates"]
    if metadata["wikidata_id"]:
        payload["wikidata_id"] = metadata["wikidata_id"]
    if metadata["geonames_id"]:
        payload["geonames_id"] = metadata["geonames_id"]
    if concept_id:
        payload["concept"] = concept_id
    return payload


def get_or_create_location(
    name,
    wikidata_qid=None,
    geonames_id=None,
    *,
    locations_db=None,
    normalize_fn=None,
    concept_id=None,
):
    """Create or retrieve a LocationPoint through focused import helpers."""
    from api_client import api_get, api_patch, api_post

    if not name or str(name).strip() in ("", "nan"):
        return None
    canonical_name = canonical_location_name(name, locations_db)
    if canonical_name is None:
        return None
    name = canonical_name
    norm = normalize_fn or normalize_location
    metadata = _prepare_location_metadata(
        name,
        wikidata_qid,
        geonames_id,
        locations_db=locations_db,
        normalize_fn=normalize_fn,
    )
    key = metadata["key"] if normalize_fn is None else norm(metadata["name"])
    if key in _location_cache:
        cached_id = _location_cache[key]
        if not concept_id:
            return cached_id
        try:
            cached = api_get(f"locations/{cached_id}")
        except Exception:
            cached = None
        if cached and cached.get("concept") == concept_id:
            return cached_id
        linked = _find_concept_location(api_get, concept_id, cached_id)
        if linked:
            owner = _reconcile_concept_owner(
                api_get,
                api_patch,
                cached,
                linked,
                concept_id,
                key,
                norm,
            )
            _location_cache[key] = owner["id"]
            return owner["id"]
        if cached and not cached.get("concept"):
            api_patch("locations", cached_id, {"concept": concept_id})
        return cached_id
    try:
        existing = api_get("locations", params={"search": metadata["name"]})
    except Exception:
        logger.exception("Location API lookup failed for %s", metadata["name"])
        return None
    match = _find_location_match(existing, key, norm)
    linked = None
    if concept_id and (match is None or not match.get("concept")):
        linked = _find_concept_location(
            api_get,
            concept_id,
            match["id"] if match else None,
        )
    if linked:
        owner = _reconcile_concept_owner(
            api_get,
            api_patch,
            match,
            linked,
            concept_id,
            key,
            norm,
        )
        _location_cache[key] = owner["id"]
        return owner["id"]
    if match:
        updates = _existing_location_updates(metadata, match, concept_id)
        if updates:
            try:
                api_patch("locations", match["id"], updates)
            except Exception:
                logger.exception(
                    "Location API update failed for %s (id=%s)",
                    metadata["name"],
                    match["id"],
                )
        _location_cache[key] = match["id"]
        return match["id"]
    payload = _new_location_payload(metadata, concept_id)
    try:
        created = api_post("locations", payload, fail_on_error=False)
    except Exception:
        logger.exception("Location API create failed for %s", metadata["name"])
        return None
    if created is None:
        logger.error(
            "Skipping location %r because the API rejected it", metadata["name"]
        )
        return None
    _location_cache[key] = created["id"]
    return created["id"]


def rebuild_location_workbook(
    input_path=None, output_path=None, data_root=None, taxonomy_path=None, **kwargs
):
    """Rebuild the shared location workbook for the chronotopi import.

    The source-merging and geospatial containment implementation lives in
    ``rebuild_locations`` so it remains independently testable. This public
    wrapper makes that implementation part of the normal locations API and
    gives the chronotopi notebook one authoritative import entry point.
    """
    from pathlib import Path
    from rebuild_locations import rebuild_workbook

    arguments = dict(kwargs)
    if input_path is not None:
        arguments["input_path"] = Path(input_path)
    if output_path is not None:
        arguments["output_path"] = Path(output_path)
    if data_root is not None:
        arguments["data_root"] = Path(data_root)
    if taxonomy_path is not None:
        arguments["taxonomy_path"] = Path(taxonomy_path)
    return rebuild_workbook(**arguments)


def sync_location_concepts(resolve_location, *, api_get=None, api_patch=None):
    """Attach every resolvable imported location point to its GO concept.

    This runs after taxonomy creation so metadata points created earlier and
    chronotopi points created later share the same canonical concept IDs.
    Existing concepts are preserved; reviewed exclusions are left untouched.
    """
    if api_get is None or api_patch is None:
        from api_client import api_get as default_get, api_patch as default_patch

        api_get = api_get or default_get
        api_patch = api_patch or default_patch

    matched = []
    unmapped = []
    locations = api_get("locations")
    concept_owners = {
        location["concept"]: location["id"]
        for location in locations
        if location.get("concept")
    }
    for location in locations:
        if location.get("concept"):
            continue
        concept_id = _resolve_exact_location(
            resolve_location, location.get("current_name", "")
        )
        if concept_id is None:
            unmapped.append(location.get("current_name", ""))
            continue
        if concept_id in concept_owners:
            unmapped.append(location.get("current_name", ""))
            continue
        api_patch("locations", location["id"], {"concept": concept_id})
        concept_owners[concept_id] = location["id"]
        matched.append((location["id"], concept_id))
    return {"matched": matched, "unmapped": unmapped}


def seed_location_entities(locations_db, resolve_location=None):
    """Ensure every rebuilt workbook row has one imported API entity.

    Metadata points are created before chronotopi runs, so this step reuses
    exact metadata names, creates missing canonical workbook entities, and
    attaches the shared GO concept whenever the taxonomy resolves the name.
    """
    from api_client import api_get, api_patch

    resolved_entries = []
    for _, entry in sorted(locations_db.items()):
        name = entry.get("name")
        if not name:
            continue
        concept_id = (
            _resolve_exact_location(resolve_location, name)
            if resolve_location
            else None
        )
        if (
            resolve_location
            and concept_id is None
            and not taxonomy_match_excluded(name)
        ):
            raise RuntimeError(f"Canonical location {name!r} has no GO concept mapping")
        resolved_entries.append((name, entry, concept_id))

    created_or_reused = []
    concept_owners = {
        location["concept"]: location["id"]
        for location in api_get("locations")
        if location.get("concept")
    }
    for name, entry, concept_id in resolved_entries:
        location_id = get_or_create_location(
            name,
            wikidata_qid=entry.get("wikidata_id"),
            geonames_id=entry.get("geonames_id"),
            locations_db=locations_db,
            concept_id=concept_id,
        )
        if location_id is not None:
            if concept_id:
                owner_id = concept_owners.get(concept_id)
                if owner_id and owner_id != location_id:
                    api_patch("locations", owner_id, {"concept": None})
                api_patch("locations", location_id, {"concept": concept_id})
                concept_owners[concept_id] = location_id
                refreshed = api_get(f"locations/{location_id}")
                if refreshed.get("concept") != concept_id:
                    raise RuntimeError(
                        f"Location {name!r} did not retain concept {concept_id}"
                    )
            created_or_reused.append((name, location_id, concept_id))
    return created_or_reused


def _resolve_exact_location(resolve_location, name):
    """Resolve a canonical label with aliases enabled but embedded matching off."""
    try:
        return resolve_location(
            name,
            allow_aliases=True,
            allow_embedded=False,
        )
    except TypeError:
        # Supplemental-concept resolvers expose a one-argument interface and
        # apply the same exact-or-alias rule internally.
        return resolve_location(name)


def link_locations_to_regions(locations_db):
    """Create LocationRegions from super_region data and link LocationPoints."""
    from api_client import api_get, api_bulk_upsert, api_bulk_update

    xlsx_path = LOCATIONS_WORKBOOK_PATH
    if not os.path.exists(xlsx_path):
        print("  locations.xlsx not found, skipping region linking")
        return

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws is not None, "locations.xlsx has no active sheet"
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    sr_col = (headers.index("super_region") + 1) if "super_region" in headers else None
    if not sr_col:
        print("  No super_region column in locations.xlsx, skipping")
        return

    # Collect location→super_region pairs
    pairs = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(r, 1).value
        sr = ws.cell(r, sr_col).value
        if name and sr and str(sr).strip() not in ("", "nan"):
            pairs.append((str(name).strip(), str(sr).strip()))

    # Bulk-upsert all unique regions
    unique_regions = sorted(set(sr for _, sr in pairs))
    if unique_regions:
        region_items = [{"name": rn} for rn in unique_regions]
        api_bulk_upsert("regions", region_items)

    # Build region name→id map
    all_regions = api_get("regions")
    region_map = {r["name"].strip().lower(): r["id"] for r in all_regions}

    # Build location name→id map
    all_locs = api_get("locations")
    loc_map = {loc["current_name"].strip().lower(): loc for loc in all_locs}

    # Bulk-update locations with region IDs
    updates = []
    for loc_name, region_name in pairs:
        loc = loc_map.get(loc_name.strip().lower())
        region_id = region_map.get(region_name.strip().lower())
        if loc and region_id and loc.get("region") != region_id:
            updates.append({"id": loc["id"], "region": region_id})

    if updates:
        result = api_bulk_update("locations", updates)
        print(
            f"  Linked {result['updated']} locations to regions "
            f"({len(unique_regions)} regions)"
        )
    else:
        print("  No region updates needed")
