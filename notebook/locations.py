import logging
import os
import time
import math
import openpyxl
import requests
import regex as re
from typing import Any

from utils import extract_id_from_url, is_empty


logger = logging.getLogger(__name__)


GEONAMES_USERNAME = "mapto"

domains = ["geonames.org", "wikidata.org"]


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
            logger.warning("Invalid coordinates embedded in GeoNames URL %s: %s", url, exc)
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
    name = str(name).strip().lower()
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(sorted(name.split()))


def load_locations_db(xlsx_path=None, *, enrich_coordinates=True, save_enriched=True):
    """Load locations.xlsx and optionally backfill missing coordinates.

    Coordinates already present in the workbook always win. Missing pairs are
    resolved from GeoNames first and Wikidata second, then persisted back to
    the same workbook when ``save_enriched`` is true.
    """
    if xlsx_path is None:
        xlsx_path = os.path.join(
            os.path.dirname(__file__) if "__file__" in dir() else ".",
            "locations.xlsx",
        )
    if not os.path.exists(xlsx_path):
        logger.warning("locations.xlsx not found at %s, starting fresh", xlsx_path)
        return _locations_db
    _locations_db.clear()
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws is not None
    for r in range(2, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not name:
            continue
        key = normalize_location(name)
        wikidata_url = str(ws.cell(r, 8).value or "").strip()
        geonames_url = str(ws.cell(r, 7).value or "").strip()
        extra_url = str(ws.cell(r, 9).value or "").strip()
        _locations_db[key] = {
            "name": str(name).strip(),
            "lat": ws.cell(r, 4).value,
            "long": ws.cell(r, 5).value,
            "label": str(ws.cell(r, 6).value or "").strip(),
            "wikidata_id": extract_id_from_url(wikidata_url),
            "geonames_id": extract_geonames_id(geonames_url),
            "wikidata_url": wikidata_url
            if wikidata_url and wikidata_url != "nan"
            else "",
            "geonames_url": geonames_url
            if geonames_url and geonames_url != "nan"
            else "",
            "extra_url": extra_url if extra_url and extra_url != "nan" else "",
        }
    if enrich_coordinates:
        changed = False
        for entry in _locations_db.values():
            before = _coordinate_pair(entry)
            # Coordinates in the workbook are the trusted local cache. Do not
            # query external providers when both cached values are present.
            after = before if before is not None else resolve_location_coordinates(entry)
            if after is not None and after != before:
                changed = True
        if changed and save_enriched:
            save_locations_db(xlsx_path)
    print(f"  Loaded {len(_locations_db)} locations from locations.xlsx")
    return _locations_db


def save_locations_db(xlsx_path=None):
    """Save _locations_db back to locations.xlsx, merging with existing data."""
    if xlsx_path is None:
        xlsx_path = os.path.join(
            os.path.dirname(__file__) if "__file__" in dir() else ".",
            "locations.xlsx",
        )
    HEADERS = [
        "location",
        "bag_of_words",
        "super_region",
        "lat",
        "long",
        "label",
        "www.geonames.org",
        "www.wikidata.org",
        "www.giessen.de",
    ]
    FIELD_COL = {
        1: "name",
        4: "lat",
        5: "long",
        6: "label",
        7: "geonames_url",
        8: "wikidata_url",
        9: "extra_url",
    }

    if os.path.exists(xlsx_path):
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        assert ws is not None
        existing_rows = {}
        for r in range(2, ws.max_row + 1):
            name = ws.cell(r, 1).value
            if name:
                existing_rows[normalize_location(name)] = r
        added = 0
        for key in sorted(_locations_db.keys()):
            loc = _locations_db[key]
            if key in existing_rows:
                row_num = existing_rows[key]
                for col_idx, field in FIELD_COL.items():
                    if col_idx == 1:
                        continue
                    if is_empty(ws.cell(row_num, col_idx).value):
                        new_val = loc.get(field)
                        if not is_empty(new_val):
                            ws.cell(row_num, col_idx).value = new_val
            else:
                ws.append(
                    [
                        loc["name"],
                        "",
                        "",
                        loc.get("lat") or "",
                        loc.get("long") or "",
                        loc.get("label", ""),
                        loc.get("geonames_url", ""),
                        loc.get("wikidata_url", ""),
                        loc.get("extra_url", ""),
                    ]
                )
                added += 1
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(HEADERS)
        added = 0
        for key in sorted(_locations_db.keys()):
            loc = _locations_db[key]
            ws.append(
                [
                    loc["name"],
                    "",
                    "",
                    loc.get("lat") or "",
                    loc.get("long") or "",
                    loc.get("label", ""),
                    loc.get("geonames_url", ""),
                    loc.get("wikidata_url", ""),
                    loc.get("extra_url", ""),
                ]
            )
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
        "extra_url": "",
    }


# ---------------------------------------------------------------------------
# Location API operations (get-or-create, region linking)
# ---------------------------------------------------------------------------

_location_cache = {}


def get_or_create_location(
    name, wikidata_qid=None, geonames_id=None, *, locations_db=None, normalize_fn=None
):
    """Create or retrieve a LocationPoint, using locations_db for coordinates."""
    from api_client import api_get, api_patch, api_post

    if not name or str(name).strip() in ("", "nan"):
        return None
    name = str(name).strip()
    norm = normalize_fn or normalize_location
    key = norm(name)
    if key in _location_cache:
        return _location_cache[key]
    db_entry = dict((locations_db or {}).get(key, {}))
    db_entry.setdefault("name", name)
    if wikidata_qid and not db_entry.get("wikidata_url"):
        db_entry["wikidata_url"] = f"https://www.wikidata.org/wiki/{wikidata_qid}"
    if geonames_id and not db_entry.get("geonames_url"):
        db_entry["geonames_url"] = f"https://www.geonames.org/{geonames_id}"
    # A complete workbook cache wins and must not trigger external lookups.
    coordinates = _coordinate_pair(db_entry)
    if coordinates is None:
        coordinates = resolve_location_coordinates(db_entry)
    wid = db_entry.get("wikidata_id") or (
        wikidata_qid if wikidata_qid and wikidata_qid not in ("", "nan") else None
    )
    gid = (
        extract_geonames_id(db_entry.get("geonames_id"))
        or extract_geonames_id(db_entry.get("geonames_url"))
        or extract_geonames_id(geonames_id)
    )
    try:
        existing = api_get("locations", params={"search": name})
    except Exception:
        logger.exception("Location API lookup failed for %s", name)
        return None
    match = next((loc for loc in existing if norm(loc["current_name"]) == key), None)
    if match:
        updates = {}
        if coordinates is not None and not match.get("location"):
            updates["latitude"], updates["longitude"] = coordinates
        if wid and not match.get("wikidata_id"):
            updates["wikidata_id"] = wid
        if gid and not match.get("geonames_id"):
            updates["geonames_id"] = gid
        if updates:
            try:
                api_patch("locations", match["id"], updates)
            except Exception:
                logger.exception(
                    "Location API update failed for %s (id=%s)", name, match["id"]
                )
        _location_cache[key] = match["id"]
        return match["id"]
    payload: dict[str, Any] = {"current_name": name}
    if coordinates is not None:
        payload["latitude"], payload["longitude"] = coordinates
    if wid:
        payload["wikidata_id"] = wid
    if gid:
        payload["geonames_id"] = gid
    try:
        created = api_post("locations", payload, fail_on_error=False)
    except Exception:
        logger.exception("Location API create failed for %s", name)
        return None
    if created is None:
        logger.error("Skipping location %r because the API rejected it", name)
        return None
    _location_cache[key] = created["id"]
    return created["id"]


def link_locations_to_regions(locations_db):
    """Create LocationRegions from super_region data and link LocationPoints."""
    from api_client import api_get, api_bulk_upsert, api_bulk_update

    xlsx_path = os.path.join(
        os.path.dirname(__file__) if "__file__" in dir() else ".",
        "locations.xlsx",
    )
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
