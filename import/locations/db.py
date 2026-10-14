"""Load, save, and extend the locations workbook and its in-memory database.

``import/locations.xlsx`` (``LOCATIONS_WORKBOOK_PATH``) is the shared table of
location coordinates and source URLs. The import reads it into ``_locations_db``,
keyed by ``normalize_location``, backfills missing coordinates, and writes the
results back, so coordinates found on one run are not looked up again on the
next.

``load_locations_db`` is called by the chronotopi notebook and by
``metadati.places``, which turns coordinate lookups off. ``save_locations_db``
runs after the backfill. ``rebuild_location_workbook`` delegates to
``rebuild_locations``. ``link_locations_to_regions`` pushes super-region links to
the API, and ``upsert_location_db`` records new IDs in memory. Only the active
sheet is read and written.
"""

import logging
import os
import openpyxl
from pathlib import Path
from utils import extract_id_from_url, is_empty
from locations.names import normalize_location
from locations.geo import (
    _coordinate_pair,
    extract_geonames_id,
    resolve_location_coordinates,
)

logger = logging.getLogger(__name__)

LOCATIONS_WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "locations.xlsx"


# ---------------------------------------------------------------------------
# Locations database (locations.xlsx) — load, save, upsert
# ---------------------------------------------------------------------------

# Column layout (1-indexed):
#   1: location, 2: bag_of_words, 3: super_region,
#   4: lat, 5: long, 6: label,
#   7: www.geonames.org, 8: www.wikidata.org, 9+: other URLs

_locations_db = {}  # normalize_location(name) -> {name, lat, long, ...}


def load_locations_db(xlsx_path=None, *, enrich_coordinates=True, save_enriched=True):
    """Load locations.xlsx into ``_locations_db`` and optionally backfill coordinates.

    Each row with a name becomes a record keyed by ``normalize_location``. A later
    row with the same key replaces an earlier one. A record holds ``name``,
    ``lat``, ``long``, the Wikidata and GeoNames IDs and URLs, and ``extra_url``,
    which maps each populated column after ``www.geonames.org`` to its URL.
    Coordinates already in the workbook always win. With ``enrich_coordinates``,
    missing pairs go through ``resolve_location_coordinates``, which may make
    network requests. With ``save_enriched``, the workbook is rewritten when any
    pair was added.

    The function clears ``_locations_db``, refills it, and returns that same dict.
    A missing file logs a warning and returns the dict as it is. A one-line summary
    is printed. The chronotopi notebook and ``metadati.places`` call this function.

    Args:
        xlsx_path: Workbook to read. Defaults to ``LOCATIONS_WORKBOOK_PATH``.
        enrich_coordinates: Look up missing coordinates. False skips the lookups.
        save_enriched: Write the workbook back after new coordinates are found.
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
        """Collect every populated workbook column after the GeoNames column.

        Columns to the right of ``www.geonames.org`` hold extra source URLs, such as
        Wikidata links and archive pages. Blank cells and the strings ``nan`` and
        ``none`` are skipped. Returns a dict from header to URL for this row, or an
        empty dict when the GeoNames column is absent.
        """
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
    """Normalize extra_url to a mapping of workbook headers to URL values.

    Each record keeps its extra URLs keyed by workbook header, so a value written
    back must go to the column with that header. Accepted shapes are a dict keyed
    by header (as ``load_locations_db`` builds), a list or tuple whose entries are
    named ``extra_url_1``, ``extra_url_2``, and so on by position, and a single
    value stored under ``extra_url``. Blank entries are dropped, and blank input
    gives an empty dict. Used by ``save_locations_db``.
    """
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
    """Save _locations_db back to locations.xlsx, merging with existing data.

    When the file exists, each record is matched to its row by normalized name,
    and only empty cells are filled, so values already in the workbook are kept.
    Records with no row are appended in key order, and missing extra URL headers
    get new columns. When the file does not exist, a workbook is created with the
    standard headers, one column per extra URL header, and one row per record.
    Openpyxl errors propagate. A one-line summary is printed. Called by
    ``load_locations_db`` after a backfill.
    """
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
    """Add location to the database if not already present.

    Meant for code that learns a Wikidata QID or GeoNames ID during an import and
    wants the next ``save_locations_db`` call to persist it. Blank names and
    ``nan`` are ignored. An existing record receives the QID or ID, and its URL,
    only when it has none, so stored values are not overwritten. A new record has
    no coordinates. This function does not write the workbook, and no caller in
    ``import/`` uses it at present.
    """
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


def rebuild_location_workbook(
    input_path=None, output_path=None, data_root=None, taxonomy_path=None, **kwargs
):
    """Rebuild the shared location workbook for the chronotopi import.

    The source-merging and geospatial containment implementation lives in
    ``rebuild_locations`` so it remains independently testable. This public
    wrapper makes that implementation part of the normal locations API and
    gives the chronotopi notebook one authoritative import entry point.

    Path arguments are converted to ``Path``, and everything else is forwarded.
    Unset paths take the ``rebuild_locations`` defaults. The default output is the
    input workbook, so the call rewrites ``import/locations.xlsx`` in place.
    Coordinates may be fetched over the network. The rebuild raises
    ``RuntimeError`` and writes nothing when a retained row lacks valid
    coordinates or no rows remain.

    Returns the counts from ``rebuild_workbook``: ``rows``, ``dropped``, and
    ``coordinates_<source>`` for each coordinate source. The notebook reads
    ``rows``.

    Args:
        input_path: Existing workbook to merge from. Defaults to
            ``import/locations.xlsx``.
        output_path: Workbook to write. Defaults to the input path.
        data_root: Folder of source workbooks. Defaults to ``data/nuove schede``.
        taxonomy_path: MAXQDA taxonomy used for containment.
        **kwargs: Forwarded to ``rebuild_workbook``, for example ``own_geocoder``.
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


def link_locations_to_regions(locations_db):
    """Create LocationRegions from super_region data and link LocationPoints.

    The ``locations_db`` argument is accepted but never read: the function reads
    ``LOCATIONS_WORKBOOK_PATH`` from disk. Each distinct ``super_region`` name is
    bulk-upserted as an API region. Each workbook location is then matched to an
    API location by name, ignoring case and surrounding spaces, and its region is
    set through one bulk update when it differs. A missing workbook or
    ``super_region`` column prints a note and returns. Returns None. No caller in
    ``import/`` uses this function at present.
    """
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
