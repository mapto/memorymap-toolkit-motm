"""Integration tests for events.create_event_from_row() against a live
Memory Map Toolkit instance (Django + PostGIS), e.g. the docker-compose
stack (`docker compose up`) or `manage.py runserver`.

These tests perform real HTTP requests against the API (login via
admin/admin, same as the notebook pipeline), create real database rows,
verify them via a *fresh* GET request — proving the data was actually
persisted, not just echoed back by the POST response — and delete
everything they created afterwards.

Concepts are intentionally never deleted: get_or_create_concept() matches
existing taxonomy entries by label, so a test payload may resolve to a
concept shared with real data; deleting it would corrupt other records.

Automatically skipped when the server is unreachable.
"""

import uuid

import pytest
import requests

import api_client
import events


def _server_available():
    try:
        requests.get(api_client.LOGIN_URL, timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason=f"MMT server not reachable at {api_client.LOGIN_URL}",
)


@pytest.fixture(scope="module", autouse=True)
def logged_in():
    assert api_client.login(), "Could not authenticate against the live MMT API"


@pytest.fixture
def cleanup():
    """Collects (endpoint, id) pairs to delete after the test, in reverse
    order (dependents before the objects they reference)."""
    created = []
    yield created
    for endpoint, obj_id in reversed(created):
        try:
            api_client.api_delete(endpoint, obj_id)
        except Exception:
            pass


def unique(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


class TestCreateEventFromRowIntegration:
    def test_full_event_is_persisted_with_all_fields(self, cleanup):
        label = unique("IT Alte Heimat Geburt")
        person = unique("IT Person")
        place = unique("IT Giessen")
        link = f"https://example.com/{uuid.uuid4().hex}"

        row = {
            "event_label": label,
            "event_type": "birth",
            "place_name": place,
            "place_detail": "Marktplatz 11",
            "place_category": "alte_heimat",
            "wikidata_qid": "",
            "geonames_id": "",
            "date_start": "1921-06-15",
            "date_end": "",
            "date_certainty": "certain",
            "transport_mode": "",
            "external_links": link,
        }

        event_id = events.create_event_from_row(row, person, start_location=place)
        assert event_id is not None
        cleanup.append(("events", event_id))

        # Re-fetch independently of the POST response to prove persistence.
        fetched = api_client.api_get(f"events/{event_id}")
        assert fetched["description"] == label
        assert fetched["lifecycle"] == "alte_heimat"
        assert fetched["is_confirmed"] is True
        assert fetched["timespan"] is not None
        assert fetched["end_location"] is not None
        assert fetched["persons"], "protagonist should be linked as a Person"
        assert fetched["concepts"], "event_type/place_category should be linked as Concepts"
        assert fetched["urls"], "external_links should be linked as URLs"

        timespan = api_client.api_get(f"timespans/{fetched['timespan']}")
        assert timespan["start"] == "1921-06-15"
        assert timespan["certainty"] == "certain"

        location = api_client.api_get(f"locations/{fetched['end_location']}")
        assert location["current_name"] == f"{place} (Marktplatz 11)"

        person_obj = api_client.api_get(f"persons/{fetched['persons'][0]}")
        assert person == f"{person_obj['given_name']} {person_obj['family_name']}"

        url_obj = api_client.api_get(f"urls/{fetched['urls'][0]}")
        assert url_obj["url"] == link

        # Register the objects this test itself created for cleanup.
        # (Concepts are deliberately excluded, see module docstring.)
        cleanup.append(("timespans", fetched["timespan"]))
        cleanup.append(("locations", fetched["end_location"]))
        if fetched["start_location"] and fetched["start_location"] != fetched["end_location"]:
            cleanup.append(("locations", fetched["start_location"]))
        for pid in fetched["persons"]:
            cleanup.append(("persons", pid))
        cleanup.append(("urls", fetched["urls"][0]))

    def test_uncertain_event_without_dates_has_no_timespan(self, cleanup):
        label = unique("IT Undated event")
        place = unique("IT Nowhere")

        row = {
            "event_label": label,
            "event_type": "residence",
            "place_name": place,
            "date_start": "",
            "date_end": "",
            "date_certainty": "",
            "place_category": "neue_heimat",
        }

        event_id = events.create_event_from_row(row, unique("IT Person"))
        assert event_id is not None
        cleanup.append(("events", event_id))

        fetched = api_client.api_get(f"events/{event_id}")
        assert fetched["timespan"] is None
        assert fetched["is_confirmed"] is False
        assert fetched["lifecycle"] == "neue_heimat"

        cleanup.append(("locations", fetched["end_location"]))
        for pid in fetched["persons"]:
            cleanup.append(("persons", pid))

    def test_journey_links_distinct_start_and_end_locations(self, cleanup):
        start_place = unique("IT Gießen")
        end_place = unique("IT Schlesien")
        label = unique("IT Hachschara")

        row = {
            "event_label": label,
            "event_type": "education",
            "place_name": end_place,
            "date_start": "1935",
            "date_certainty": "probable",
            "place_category": "alte_heimat",
        }

        event_id = events.create_event_from_row(
            row, unique("IT Person"), start_location=start_place
        )
        assert event_id is not None
        cleanup.append(("events", event_id))

        fetched = api_client.api_get(f"events/{event_id}")
        assert fetched["start_location"] is not None
        assert fetched["end_location"] is not None
        assert fetched["start_location"] != fetched["end_location"]

        start_loc = api_client.api_get(f"locations/{fetched['start_location']}")
        end_loc = api_client.api_get(f"locations/{fetched['end_location']}")
        assert start_loc["current_name"] == start_place
        assert end_loc["current_name"] == end_place

        cleanup.append(("timespans", fetched["timespan"]))
        cleanup.append(("locations", fetched["start_location"]))
        cleanup.append(("locations", fetched["end_location"]))
        for pid in fetched["persons"]:
            cleanup.append(("persons", pid))


class TestDatabaseConsistency:
    """Verifies that repeated get_or_create-style calls don't fork duplicate
    Person/Location rows, and that created events are consistently visible
    through the list endpoint (not just the single-object GET)."""

    def test_same_protagonist_and_place_are_not_duplicated_across_events(self, cleanup):
        person = unique("IT Person")
        place = unique("IT SamePlace")

        row1 = {
            "event_label": unique("IT Event A"), "place_name": place,
            "event_type": "residence", "place_category": "neue_heimat",
        }
        row2 = {
            "event_label": unique("IT Event B"), "place_name": place,
            "event_type": "residence", "place_category": "neue_heimat",
        }

        event_id_1 = events.create_event_from_row(row1, person)
        event_id_2 = events.create_event_from_row(row2, person)
        assert event_id_1 is not None and event_id_2 is not None
        assert event_id_1 != event_id_2
        cleanup.append(("events", event_id_1))
        cleanup.append(("events", event_id_2))

        fetched1 = api_client.api_get(f"events/{event_id_1}")
        fetched2 = api_client.api_get(f"events/{event_id_2}")

        # Two distinct Events, but the same underlying Person, Location and
        # Concept rows should be reused rather than duplicated.
        assert fetched1["persons"] == fetched2["persons"]
        assert fetched1["end_location"] == fetched2["end_location"]
        assert fetched1["concepts"] == fetched2["concepts"]

        cleanup.append(("locations", fetched1["end_location"]))
        for pid in fetched1["persons"]:
            cleanup.append(("persons", pid))

    def test_created_event_is_visible_and_unique_in_list_endpoint(self, cleanup):
        label = unique("IT ListVisibility")
        row = {
            "event_label": label, "place_name": unique("IT SomePlace"),
            "event_type": "residence", "place_category": "neue_heimat",
        }

        event_id = events.create_event_from_row(row, unique("IT Person"))
        assert event_id is not None
        cleanup.append(("events", event_id))
        fetched = api_client.api_get(f"events/{event_id}")
        cleanup.append(("locations", fetched["end_location"]))
        for pid in fetched["persons"]:
            cleanup.append(("persons", pid))

        all_events = api_client.api_get("events")
        matches = [e for e in all_events if e["description"] == label]
        assert len(matches) == 1, "event should appear exactly once in the list endpoint"
        assert matches[0]["id"] == event_id
