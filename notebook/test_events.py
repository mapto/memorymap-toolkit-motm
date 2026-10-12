"""Unit tests for events.create_event_from_row().

Replicates the dataframe-preparation logic from the "Put all data together"
cell of chronotopi.ipynb against a real sample workbook, then exercises
create_event_from_row() with every network-touching dependency mocked out
(no live server / DB access needed). See test_events_integration.py for
end-to-end tests against a running Memory Map Toolkit instance.
"""

from pathlib import Path

import pandas as pd
import pytest

import events

DATA_FILE = (
    Path(__file__).parent.parent
    / "data" / "nuove schede" / "chronotopoi_josef_stern_familie_v4a.xlsx"
)
SHEET_NAME = "Josef Stern"


def build_person_dataframe(path=DATA_FILE, sheet=SHEET_NAME):
    """Replicate the chronotopi.ipynb dataframe-prep cell for one sheet.

    Mirrors: reading past the vocabulary header rows (skiprows=2), casting
    every column to str, and deriving start_location/end_location by
    tracking the previous row's place per protagonist.
    """
    df = pd.read_excel(path, sheet_name=sheet, skiprows=2)
    df["name"] = sheet
    df = df.astype(str)
    df.fillna("", inplace=True)

    start_locations = []
    prev_location = {}
    for _, row in df.iterrows():
        person = row["name"]
        end_loc = row["place_name"].strip()
        start_loc = prev_location.get(person, end_loc)
        start_locations.append(start_loc)
        if end_loc:
            prev_location[person] = end_loc
    df["start_location"] = start_locations
    df["end_location"] = df["place_name"]
    return df


@pytest.fixture(scope="module")
def person_df():
    if not DATA_FILE.exists():
        pytest.skip(f"sample workbook not found: {DATA_FILE}")
    return build_person_dataframe()


def row_by_label(df, label, occurrence=0):
    matches = df[df["event_label"] == label]
    return matches.iloc[occurrence].to_dict()


@pytest.fixture
def api_stub(monkeypatch):
    """Stub out every network-touching dependency of create_event_from_row."""
    calls = {
        "locations": [], "location_kwargs": {}, "timespans": [], "concepts": [],
        "persons": [], "urls": [], "posted": [],
    }

    def fake_location(name, wikidata_qid=None, geonames_id=None, locations_db=None):
        calls["locations"].append(name)
        calls["location_kwargs"][name] = {
            "wikidata_qid": wikidata_qid, "geonames_id": geonames_id,
        }
        return f"loc:{name}"

    def fake_timespan(start, end, certainty=None):
        calls["timespans"].append((start, end, certainty))
        return "timespan:1"

    def fake_concept(label):
        calls["concepts"].append(label)
        return f"concept:{label}"

    def fake_person(protagonist_col, name_col):
        calls["persons"].append((protagonist_col, name_col))
        return "person:1"

    def fake_url(url_str):
        calls["urls"].append(url_str)
        return f"url:{url_str}"

    def fake_api_post(endpoint, payload, fail_on_error=True):
        calls["posted"].append((endpoint, payload))
        return {"id": 42, **payload}

    monkeypatch.setattr(events, "get_or_create_location", fake_location)
    monkeypatch.setattr(events, "get_or_create_timespan", fake_timespan)
    monkeypatch.setattr(events, "get_or_create_concept", fake_concept)
    monkeypatch.setattr(events, "get_person_id", fake_person)
    monkeypatch.setattr(events, "get_or_create_url", fake_url)
    monkeypatch.setattr(events, "api_post", fake_api_post)
    return calls


class TestEventHelpers:
    def test_prepare_event_data_normalizes_location_and_rejects_missing_fields(self):
        assert events.prepare_event_data({"event_label": "", "place_name": "Place"}) is None
        assert events.prepare_event_data({"event_label": "Event", "place_name": ""}) is None

        assert events.prepare_event_data(
            {"event_label": "Event", "place_name": "Place", "place_detail": "Room"}
        ) == {
            "event_label": "Event",
            "place_name": "Place",
            "location_name": "Place (Room)",
        }

    def test_resolve_event_concepts_includes_time_and_person(self):
        row = {
            "event_type": "birth",
            "transport_mode": "train",
            "place_category": "alte_heimat",
            "date_label": "1933",
        }
        def resolve(label):
            return f"concept:{label}"

        assert events.resolve_event_concepts(
            row,
            protagonist="Ada",
            concept_resolver=resolve,
            time_concept_resolver=lambda label: f"time:{label}",
            person_concept_resolver=lambda label: f"person:{label}",
        ) == [
            "concept:birth",
            "concept:train",
            "concept:alte_heimat",
            "time:1933",
            "person:Ada",
        ]

    def test_create_event_timespan_preserves_certainty(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            events,
            "get_or_create_timespan",
            lambda start, end, certainty=None: calls.append((start, end, certainty)) or 7,
        )

        timespan_id, certainty = events.create_event_timespan(
            {"date_start": "1933", "date_end": "", "date_certainty": "probable"}
        )

        assert timespan_id == 7
        assert certainty == "probable"
        assert calls == [("1933-01-01", None, "probable")]

    def test_build_event_payload_omits_empty_relationships(self):
        payload = events.build_event_payload(
            {"event_label": "Event"},
            "altro",
            "certain",
            None,
            "location:1",
            None,
            None,
            ["concept:1"],
            [],
        )

        assert payload == {
            "description": "Event",
            "lifecycle": "altro",
            "is_confirmed": True,
            "end_location": "location:1",
            "concepts": ["concept:1"],
        }


class TestCreateEventFromRowPayload:
    def test_birth_event_populates_all_fields(self, person_df, api_stub):
        row = row_by_label(person_df, "Alte Heimat Geburt")

        event_id = events.create_event_from_row(
            row, "Josef Stern", start_location=row["start_location"]
        )

        assert event_id == 42
        endpoint, payload = api_stub["posted"][0]
        assert endpoint == "events"
        assert payload["description"] == "Alte Heimat Geburt"
        assert payload["lifecycle"] == "alte_heimat"
        assert payload["is_confirmed"] is True  # date_certainty == "certain"
        assert payload["timespan"] == "timespan:1"
        assert api_stub["timespans"] == [("1921-06-15", None, "certain")]
        assert payload["end_location"] == "loc:Gießen (Marktplatz 11)"
        # start_location ("Gießen") differs from the detailed end_location
        # name ("Gießen (Marktplatz 11)"), so it is linked as a separate point.
        assert payload["start_location"] == "loc:Gießen"
        assert payload["persons"] == ["person:1"]
        assert api_stub["persons"] == [("Josef Stern", "Josef Stern")]
        assert payload["concepts"] == ["concept:birth", "concept:alte_heimat"]
        assert len(payload["urls"]) == 3  # geonames, wikidata, giessen.de

    def test_uncertain_event_is_not_confirmed_and_has_single_url(self, person_df, api_stub):
        row = row_by_label(person_df, "Wohnort", occurrence=0)

        events.create_event_from_row(row, "Josef Stern", start_location=row["start_location"])

        _, payload = api_stub["posted"][0]
        assert payload["is_confirmed"] is False
        assert payload["lifecycle"] == "alte_heimat"
        assert len(payload["urls"]) == 1

    def test_start_location_included_when_journey_moves(self, person_df, api_stub):
        row = row_by_label(person_df, "Hachschara")
        assert row["start_location"] != row["end_location"]

        events.create_event_from_row(row, "Josef Stern", start_location=row["start_location"])

        _, payload = api_stub["posted"][0]
        assert payload["end_location"] == "loc:Schlesien"
        assert payload["start_location"] == "loc:Gießen"
        assert "urls" not in payload  # no external_links on this row

    def test_lifecycle_falls_back_to_event_label_when_categories_are_ambiguous(self, person_df, api_stub):
        row = row_by_label(person_df, "Auswanderung", occurrence=0)

        events.create_event_from_row(row, "Josef Stern", start_location=row["start_location"])

        _, payload = api_stub["posted"][0]
        assert payload["lifecycle"] == "auswanderung"
        assert payload["concepts"] == [
            "concept:emigration_transit", "concept:Zug", "concept:verkehrsmittel"
        ]

    def test_missing_event_label_skips_creation(self, api_stub):
        row = {"event_label": "", "place_name": "Gießen"}
        assert events.create_event_from_row(row, "Josef Stern") is None
        assert api_stub["posted"] == []

    def test_missing_place_name_skips_creation(self, api_stub):
        row = {"event_label": "Something", "place_name": ""}
        assert events.create_event_from_row(row, "Josef Stern") is None
        assert api_stub["posted"] == []

    def test_no_dates_means_no_timespan(self, api_stub):
        row = {
            "event_label": "Undated event", "place_name": "Nowhere",
            "date_start": "", "date_end": "", "date_certainty": "",
        }
        events.create_event_from_row(row, "Josef Stern")

        _, payload = api_stub["posted"][0]
        assert "timespan" not in payload
        assert api_stub["timespans"] == []
        assert payload["is_confirmed"] is False

    def test_wikidata_and_geonames_ids_passed_to_location(self, person_df, api_stub):
        row = row_by_label(person_df, "Alte Heimat Geburt")
        assert row["wikidata_qid"] and row["geonames_id"]  # sanity check on fixture data

        events.create_event_from_row(row, "Josef Stern", start_location=row["start_location"])

        kwargs = api_stub["location_kwargs"]["Gießen (Marktplatz 11)"]
        # geonames_id round-trips through pandas as a "N.0" float string;
        # create_event_from_row cleans it via clean_str() before use.
        assert kwargs["wikidata_qid"] == events.clean_str(row["wikidata_qid"])
        assert kwargs["geonames_id"] == events.clean_str(row["geonames_id"])

    @pytest.mark.parametrize("date_certainty,expected", [
        ("certain", True),
        ("Certain", True),  # case-insensitive
        ("probable", False),
        ("uncertain", False),
        ("disputed", False),
        ("", False),
    ])
    def test_is_confirmed_matches_date_certainty(self, api_stub, date_certainty, expected):
        row = {
            "event_label": "Event", "place_name": "Somewhere",
            "date_start": "1930", "date_certainty": date_certainty,
        }
        events.create_event_from_row(row, "Josef Stern")

        _, payload = api_stub["posted"][0]
        assert payload["is_confirmed"] is expected

    def test_concept_ids_filter_out_unresolved_categories(self, api_stub, monkeypatch):
        def fake_concept(label):
            return None if label == "unresolvable" else f"concept:{label}"

        monkeypatch.setattr(events, "get_or_create_concept", fake_concept)
        row = {
            "event_label": "Event", "place_name": "Somewhere",
            "event_type": "unresolvable", "transport_mode": "", "place_category": "alte_heimat",
        }
        events.create_event_from_row(row, "Josef Stern")

        _, payload = api_stub["posted"][0]
        assert payload["concepts"] == ["concept:alte_heimat"]

    def test_processing_entire_sheet_creates_one_event_per_valid_row(self, person_df, api_stub):
        expected = sum(
            1 for _, row in person_df.iterrows()
            if row["event_label"].strip() and row["place_name"].strip()
        )

        results = [
            events.create_event_from_row(row.to_dict(), "Josef Stern", start_location=row["start_location"])
            for _, row in person_df.iterrows()
        ]

        assert len(api_stub["posted"]) == expected
        assert sum(1 for r in results if r is not None) == expected
        # Same protagonist for every row => a single Person should be resolved/reused.
        assert len(set(api_stub["persons"])) == 1


class TestLifecycleClassification:
    """place_category is a controlled vocabulary (see the workbook's
    '_Vokabular' sheet); confirm classify_lifecycle()'s behaviour for each
    value in isolation."""

    @pytest.mark.parametrize("place_category,expected", [
        ("alte_heimat", "alte_heimat"),
        ("neue_heimat", "neue_heimat"),
        ("reise_zurueck", "reise_zurueck"),
        ("transit", "altro"),
        ("ort_der_zeit", "altro"),
        ("verkehrsmittel", "altro"),
        ("erinnerungsort", "altro"),
    ])
    def test_place_category_vocabulary(self, place_category, expected):
        assert events.classify_lifecycle(place_category) == expected
