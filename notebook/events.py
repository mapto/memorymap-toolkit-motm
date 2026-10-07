import regex as re

# import re
from fuzzywuzzy import fuzz

from taxonomy import parse_mmd_taxonomy  # noqa: F401
from api_client import (
    api_post,
    get_or_create_concept,
    get_or_create_timespan,
    get_or_create_url,
    get_person_id,
)
from locations import get_or_create_location
from timespan import parse_date
from utils import clean_str, extract_url_map


def extract_events(row: str, events: list[str]) -> list[str]:
    collected = []
    line = row.strip()
    for e in events:
        if e.lower() in line.lower():
            collected += [e]
            line = re.sub(re.escape(e), "", line, flags=re.IGNORECASE).strip()
    if line:
        collected += [line]
    return collected


# ---------------------------------------------------------------------------
# Life journey classification via fuzzywuzzy
# ---------------------------------------------------------------------------

LIFECYCLE_CANDIDATES = {
    "alte_heimat": "alte Heimat",
    "auswanderung": "Auswanderung",
    "neue_heimat": "neue Heimat",
    "reise_zurueck": "Reise zurueck",
}
LIFECYCLE_THRESHOLD = 70


def classify_lifecycle(*texts):
    """Classify life journey from one or more text values using fuzzy matching.

    Checks each text in order, returns the first strong match (>=threshold).
    Returns one of: alte_heimat, auswanderung, neue_heimat, reise_zurueck, altro.

    >>> classify_lifecycle("Alte Heimat")
    'alte_heimat'
    >>> classify_lifecycle("Alte Heimat Geburt")
    'alte_heimat'
    >>> classify_lifecycle("alter heimant")
    'alte_heimat'
    >>> classify_lifecycle("Auswanderung")
    'auswanderung'
    >>> classify_lifecycle("Neue Heimat")
    'neue_heimat'
    >>> classify_lifecycle("Neue Heimat\\nEinwanderung")
    'neue_heimat'
    >>> classify_lifecycle("Reise zurück")
    'reise_zurueck'
    >>> classify_lifecycle("Reise zurueck")
    'reise_zurueck'
    >>> classify_lifecycle("Bar Mitzvah")
    'altro'
    >>> classify_lifecycle("Transport")
    'altro'
    >>> classify_lifecycle("")
    'altro'
    >>> classify_lifecycle(None)
    'altro'
    >>> classify_lifecycle("", "nan", "Auswanderung")
    'auswanderung'
    >>> classify_lifecycle("irrelevant", "Alte Heimat")
    'alte_heimat'
    """
    for text in texts:
        if not text or str(text).strip() in ("", "nan"):
            continue
        text = str(text).strip()
        best_key = "altro"
        best_score = 0
        for key, candidate in LIFECYCLE_CANDIDATES.items():
            score = fuzz.partial_ratio(candidate.lower(), text.lower())
            if score > best_score:
                best_score = score
                best_key = key
        if best_score >= LIFECYCLE_THRESHOLD:
            return best_key
    return "altro"


def create_event_from_row(row, protagonist, locations_db=None, start_location=None):
    """Create an Event object and persist to API from a chronotopi dataframe row.

    Populates every field available on the Event model:
      - description     <- event_label
      - lifecycle       <- classify_lifecycle(place_category, event_type, event_label)
      - timespan        <- get_or_create_timespan(date_start, date_end, date_certainty)
      - is_confirmed    <- True when date_certainty == "certain"
      - end_location    <- get_or_create_location(place_name [+ place_detail])
      - start_location  <- get_or_create_location(start_location) if different from end
      - persons         <- protagonist, resolved via get_person_id
      - concepts        <- event_type, transport_mode, place_category
      - urls            <- external_links

    Args:
        row: Dict containing event data with keys: event_label, place_name, place_detail,
             event_type, transport_mode, place_category, date_start, date_end,
             date_certainty, external_links, wikidata_qid, geonames_id.
        protagonist: Person identifier (name) for this event.
        locations_db: Pre-loaded locations database for coordinate lookup.
        start_location: Name of the starting location for this event (previous event's location).

    Returns:
        Event ID if created successfully, None otherwise.
    """
    event_label = clean_str(row.get("event_label", ""))
    print(f"Creating event: {event_label}")
    if not event_label:
        print(f"Failed to create event due to missing label: {row}")
        return None

    # Create location from place_name + place_detail
    place_name = clean_str(row.get("place_name", ""))
    place_detail = clean_str(row.get("place_detail", ""))

    print(f"End place: {place_name}")
    if not place_name:
        print(f"Failed to create event due to missing location: {row}")
        return None

    # Combine place_name and place_detail if both present
    location_name = f"{place_name} ({place_detail})" if place_detail else place_name

    # Get or create end location
    location_id = get_or_create_location(
        location_name,
        wikidata_qid=clean_str(row.get("wikidata_qid", "")) or None,
        geonames_id=clean_str(row.get("geonames_id", "")) or None,
        locations_db=locations_db,
    )
    print(f"End location: [{location_id}] {location_name}")

    # Get or create start location if provided and distinct from the end location
    start_location_id = None
    start_location = clean_str(start_location) if start_location else ""
    if start_location and start_location != location_name:
        start_location_id = get_or_create_location(start_location, locations_db=locations_db)
    print(f"Start location: [{start_location_id}] {start_location}")

    # Parse dates and build a Timespan (preserving the source certainty)
    date_certainty = clean_str(row.get("date_certainty", ""))
    start_iso = parse_date(clean_str(row.get("date_start", "")))
    end_iso = parse_date(clean_str(row.get("date_end", "")))
    print(f"Dates: {start_iso}-{end_iso} ({date_certainty or 'no certainty'})")

    timespan_id = None
    if start_iso or end_iso:
        timespan_id = get_or_create_timespan(start_iso, end_iso, certainty=date_certainty or None)
    print(f"Timespan: [{timespan_id}]")

    # Classify the life-journey stage
    lifecycle = classify_lifecycle(
        row.get("place_category"), row.get("event_type"), event_label
    )
    print(f"Lifecycle: {lifecycle}")

    # Collect categories from event_type, transport_mode, place_category as Concepts
    categories = []
    for field in ["event_type", "transport_mode", "place_category"]:
        val = clean_str(row.get(field, ""))
        if val:
            categories.append(val)
    print(f"Categories: {categories}")
    concept_ids = [cid for cid in (get_or_create_concept(c) for c in categories) if cid]

    # Resolve the protagonist to a Person
    person_id = get_person_id(protagonist, protagonist)
    print(f"Person: [{person_id}] {protagonist}")

    # Extract URLs from external_links
    external_links = clean_str(row.get("external_links", ""))
    url_ids = []
    if external_links:
        url_map, _ = extract_url_map(external_links)
        for url_str in url_map.values():
            url_id = get_or_create_url(url_str)
            if url_id:
                url_ids.append(url_id)
    print(f"Links: {url_ids}")

    is_confirmed = date_certainty.lower() == "certain"

    # Build event payload with every available field
    payload = {
        "description": event_label,
        "lifecycle": lifecycle,
        "is_confirmed": is_confirmed,
    }
    if timespan_id:
        payload["timespan"] = timespan_id
    if location_id:
        payload["end_location"] = location_id
    if start_location_id:
        payload["start_location"] = start_location_id
    if person_id:
        payload["persons"] = [person_id]
    if concept_ids:
        payload["concepts"] = concept_ids
    if url_ids:
        payload["urls"] = url_ids

    print(f"Payload: {payload}")
    # Create event via API
    try:
        event = api_post("events", payload, fail_on_error=False)
        if event is None:
            print(f"Failed to create event: {event_label}")
            return None
        return event.get("id")
    except Exception as e:
        print(f"Error creating event {event_label}: {e}")
        return None


if __name__ == "__main__":
    event_taxonomy = parse_mmd_taxonomy("../model/tassonomia.mmd")
    events = sorted(set(event_taxonomy.keys()), key=lambda x: -len(x))
    print(event_taxonomy)
