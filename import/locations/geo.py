"""Resolve coordinates through GeoNames, Wikidata, and a local geocoder.

Workbook rows often lack latitude and longitude. This module fills them in from
the row's GeoNames or Wikidata URL, and falls back to a name query against the
whereami geocoder only when the row has no source identifier. A provider that
fails is logged and skipped, so the next source is tried. The exception is
``extract_wikidata_coordinates``, which lets HTTP errors propagate.

Callers are ``db.load_locations_db``, which backfills when the workbook is
loaded; ``entities._prepare_location_metadata``, which needs coordinates for API
payloads; and ``rebuild_locations`` and the ``location_enrich`` notebook, which
call the lookups directly. The whereami service has to run locally at
``GEOCODER_URL`` for name queries to succeed. GeoNames and Wikidata requests
time out after 10 seconds, and geocoder requests after 5.
"""

import logging
import time
import math
import requests
import regex as re
from utils import is_empty

logger = logging.getLogger(__name__)


GEONAMES_USERNAME = "mapto"

domains = ["geonames.org", "wikidata.org"]


def _coordinate_pair(entry: dict) -> tuple[float, float] | None:
    """Return a finite ``(latitude, longitude)`` pair when both values exist.

    Workbook cells arrive as strings, floats, None, or NaN, so the values are
    converted to floats. Returns None when either value is missing, is not
    numeric, or is not finite. Callers treat None as "no usable coordinates",
    and the entry itself is not modified.
    """
    raw_latitude = entry.get("lat")
    raw_longitude = entry.get("long")
    if raw_latitude is None or raw_longitude is None:
        return None
    try:
        latitude = float(raw_latitude)
        longitude = float(raw_longitude)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    return latitude, longitude


def extract_geonames_id(value) -> str | None:
    """Return the numeric GeoNames ID from an ID or GeoNames URL.

    GeoNames entity URLs end with a slug, so taking the final URL component
    would produce values such as ``republic-of-france.html`` instead of the
    API-safe ID ``3017382``. Excel can store an ID as a float, so a trailing
    ``.0`` is stripped first. Blank, ``nan``, and ``None`` values, and URLs
    without a numeric entity ID, return None. Called when the workbook is loaded,
    when API payloads are built, and by ``rebuild_locations``.

    >>> extract_geonames_id("https://www.geonames.org/2950159/berlin.html")
    '2950159'
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
    """Resolve coordinates table-first, then from source IDs, then by name.

    Coordinates already on ``entry`` win and are normalized to floats in place.
    Otherwise the GeoNames URL is tried, then the Wikidata URL. The name is sent
    to the local geocoder only when the entry has no GeoNames or Wikidata ID or
    URL. A value from any source is written back to ``entry``, so a later
    ``save_locations_db`` persists it when ``entry`` is the live workbook record.
    Callers that pass a copy, such as ``entities._prepare_location_metadata``,
    keep the value only in that copy.

    Returns the ``(latitude, longitude)`` pair, or None when no source yields
    one. Failures are logged and skipped; the function does not raise for them.
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
    """Extract coordinates from a GeoNames URL.

    Two URL shapes are handled. A map URL such as
    ``https://www.geonames.org/maps/google_52.4863_13.3602.html`` carries its
    coordinates in the path, so no request is made. An entity URL such as
    ``https://www.geonames.org/6550600/finsterwalde.html`` is looked up by its
    numeric ID in the GeoNames JSON API, using ``GEONAMES_USERNAME``. When that
    lookup fails or returns no coordinates, the public entity page is fetched and
    its embedded ``GeoCoordinates`` values are read. Network and HTTP errors are
    logged and treated as not found, so this function does not raise for them.

    Returns a dict with ``lat`` and ``long`` as floats, or None when no source
    yields coordinates. Callers are ``resolve_location_coordinates``,
    ``rebuild_locations``, and the ``location_enrich`` notebook.
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
    """Extract coordinates from a Wikidata entity URL.

    For example, ``https://www.wikidata.org/wiki/Q64``. The Q-ID is read from the
    URL, the entity is fetched from the Wikidata API, and the first ``P625``
    (coordinate location) statement gives the coordinates. This lookup comes
    after GeoNames in ``resolve_location_coordinates``.

    Returns a dict with ``lat`` and ``long``, or None when the URL has no Q-ID or
    the entity has no usable P625 value. Unlike the GeoNames lookup, HTTP errors
    and invalid JSON propagate to the caller.
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
    """Resolve *name* through the whereami multi-provider geocoder service.

    This is the last source in ``resolve_location_coordinates``, used only for
    rows with no GeoNames or Wikidata identifier. Before each request the call
    waits 1.1 seconds. It then asks the service at ``GEOCODER_URL`` for
    ``lat,long`` text and parses the first two comma-separated values.
    ``rebuild_locations`` uses it by default.

    Returns a dict with ``lat`` and ``long``, or None when the request fails or
    the reply does not parse. Failures are logged as warnings. The values are not
    checked for finiteness; ``resolve_location_coordinates`` passes them through
    ``_coordinate_pair``.
    """
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
