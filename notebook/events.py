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


def prepare_event_data(row):
    """Normalize and validate the fields required to create an event."""
    event_label = clean_str(row.get("event_label", ""))
    if not event_label:
        return None

    place_name = clean_str(row.get("place_name", ""))
    if not place_name:
        return None

    place_detail = clean_str(row.get("place_detail", ""))
    location_name = f"{place_name} ({place_detail})" if place_detail else place_name
    return {
        "event_label": event_label,
        "place_name": place_name,
        "location_name": location_name,
    }


def create_event_locations(
    row,
    event_data,
    locations_db=None,
    start_location=None,
    location_concept_resolver=None,
):
    """Create the end and optional start locations for an event."""
    location_kwargs = {
        "wikidata_qid": clean_str(row.get("wikidata_qid", "")) or None,
        "geonames_id": clean_str(row.get("geonames_id", "")) or None,
        "locations_db": locations_db,
    }
    if location_concept_resolver:
        concept_id = location_concept_resolver(event_data["place_name"])
        if concept_id:
            location_kwargs["concept_id"] = concept_id
    location_id = get_or_create_location(
        event_data["location_name"], **location_kwargs
    )

    normalized_start = clean_str(start_location) if start_location else ""
    start_location_id = None
    if normalized_start and normalized_start != event_data["location_name"]:
        start_kwargs = {"locations_db": locations_db}
        if location_concept_resolver:
            concept_id = location_concept_resolver(normalized_start)
            if concept_id:
                start_kwargs["concept_id"] = concept_id
        start_location_id = get_or_create_location(normalized_start, **start_kwargs)

    return location_id, start_location_id


def create_event_timespan(row):
    """Create the event's timespan and return it with normalized certainty."""
    date_certainty = clean_str(row.get("date_certainty", ""))
    start_iso = parse_date(clean_str(row.get("date_start", "")))
    end_iso = parse_date(clean_str(row.get("date_end", "")))
    timespan_id = None
    if start_iso or end_iso:
        timespan_id = get_or_create_timespan(
            start_iso,
            end_iso,
            certainty=date_certainty or None,
        )
    return timespan_id, date_certainty


def resolve_event_concepts(
    row,
    protagonist=None,
    concept_resolver=None,
    time_concept_resolver=None,
    person_concept_resolver=None,
):
    """Resolve source categories and the optional date label to concept IDs."""
    categories = []
    for field in ["event_type", "transport_mode", "place_category"]:
        value = clean_str(row.get(field, ""))
        if value:
            categories.append(value)

    resolver = concept_resolver or get_or_create_concept
    concept_ids = [concept_id for concept_id in (resolver(c) for c in categories) if concept_id]
    if time_concept_resolver:
        time_concept_id = time_concept_resolver(clean_str(row.get("date_label", "")))
        if time_concept_id and time_concept_id not in concept_ids:
            concept_ids.append(time_concept_id)
    if person_concept_resolver and protagonist:
        person_concept_id = person_concept_resolver(protagonist)
        if person_concept_id and person_concept_id not in concept_ids:
            concept_ids.append(person_concept_id)
    return concept_ids


def resolve_event_urls(external_links):
    """Create URLs from a source cell and return their IDs."""
    url_ids = []
    external_links = clean_str(external_links)
    if not external_links:
        return url_ids

    url_map, _ = extract_url_map(external_links)
    for url_str in url_map.values():
        url_id = get_or_create_url(url_str)
        if url_id:
            url_ids.append(url_id)
    return url_ids


def build_event_payload(
    event_data,
    lifecycle,
    date_certainty,
    timespan_id,
    location_id,
    start_location_id,
    person_id,
    concept_ids,
    url_ids,
):
    """Build the API payload, omitting optional empty relationships."""
    payload = {
        "description": event_data["event_label"],
        "lifecycle": lifecycle,
        "is_confirmed": date_certainty.lower() == "certain",
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
    return payload


def create_event_from_row(
    row,
    protagonist,
    locations_db=None,
    start_location=None,
    *,
    concept_resolver=None,
    location_concept_resolver=None,
    time_concept_resolver=None,
    person_concept_resolver=None,
):
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
    event_data = prepare_event_data(row)
    print(f"Creating event: {event_data['event_label'] if event_data else ''}")
    if event_data is None:
        print(f"Failed to create event due to missing label: {row}")
        return None
    print(f"End place: {event_data['place_name']}")

    location_id, start_location_id = create_event_locations(
        row,
        event_data,
        locations_db=locations_db,
        start_location=start_location,
        location_concept_resolver=location_concept_resolver,
    )
    print(f"End location: [{location_id}] {event_data['location_name']}")
    print(f"Start location: [{start_location_id}] {clean_str(start_location) if start_location else ''}")

    timespan_id, date_certainty = create_event_timespan(row)
    print(f"Timespan: [{timespan_id}]")

    # Classify the life-journey stage
    lifecycle = classify_lifecycle(
        row.get("place_category"), row.get("event_type"), event_data["event_label"]
    )
    print(f"Lifecycle: {lifecycle}")

    concept_ids = resolve_event_concepts(
        row,
        protagonist=protagonist,
        concept_resolver=concept_resolver,
        time_concept_resolver=time_concept_resolver,
        person_concept_resolver=person_concept_resolver,
    )

    # Resolve the protagonist to a Person
    person_id = get_person_id(protagonist, protagonist)
    print(f"Person: [{person_id}] {protagonist}")

    url_ids = resolve_event_urls(row.get("external_links", ""))
    print(f"Links: {url_ids}")

    payload = build_event_payload(
        event_data,
        lifecycle,
        date_certainty,
        timespan_id,
        location_id,
        start_location_id,
        person_id,
        concept_ids,
        url_ids,
    )

    print(f"Payload: {payload}")
    # Create event via API
    try:
        event = api_post("events", payload, fail_on_error=False)
        if event is None:
            print(f"Failed to create event: {event_data['event_label']}")
            return None
        return event.get("id")
    except Exception as e:
        print(f"Error creating event {event_data['event_label']}: {e}")
        return None


if __name__ == "__main__":
    event_taxonomy = parse_mmd_taxonomy("../model/tassonomia.mmd")
    events = sorted(set(event_taxonomy.keys()), key=lambda x: -len(x))
    print(event_taxonomy)
