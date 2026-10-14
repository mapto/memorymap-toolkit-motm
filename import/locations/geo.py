"""Coordinate resolution through GeoNames, Wikidata, and the geocoder."""

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
