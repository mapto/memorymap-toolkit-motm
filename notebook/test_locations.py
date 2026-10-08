"""Tests for location coordinate resolution and workbook backfilling."""

from openpyxl import Workbook, load_workbook

import locations


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


def write_locations(path, row):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(row)
    workbook.save(path)


def read_coordinates(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        return sheet.cell(2, 4).value, sheet.cell(2, 5).value
    finally:
        workbook.close()


def test_load_locations_prefers_table_coordinates(tmp_path, monkeypatch):
    path = tmp_path / "locations.xlsx"
    write_locations(
        path,
        [
            "Berlin",
            "berlin",
            "",
            52.5,
            13.4,
            "",
            "https://www.geonames.org/2950159/berlin.html",
            "https://www.wikidata.org/wiki/Q64",
            "",
        ],
    )
    locations._locations_db.clear()
    monkeypatch.setattr(
        locations,
        "resolve_location_coordinates",
        lambda url: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    database = locations.load_locations_db(path)

    entry = database[locations.normalize_location("Berlin")]
    assert (entry["lat"], entry["long"]) == (52.5, 13.4)
    assert read_coordinates(path) == (52.5, 13.4)


def test_extract_geonames_id_uses_numeric_url_segment():
    assert locations.extract_geonames_id(
        "https://www.geonames.org/3017382/republic-of-france.html"
    ) == "3017382"
    assert locations.extract_geonames_id("3017382") == "3017382"
    assert locations.extract_geonames_id("republic-of-france.html") is None


def test_cached_coordinates_skip_external_lookup_and_send_numeric_geonames_id(
    monkeypatch,
):
    locations._location_cache.clear()
    locations_db = {
        locations.normalize_location("Frankreich"): {
            "name": "Frankreich",
            "lat": 46,
            "long": 2,
            "geonames_id": "republic-of-france.html",
            "geonames_url": (
                "https://www.geonames.org/3017382/republic-of-france.html"
            ),
        }
    }
    posts = []
    monkeypatch.setattr(
        locations,
        "resolve_location_coordinates",
        lambda entry: (_ for _ in ()).throw(AssertionError("lookup should not run")),
    )
    monkeypatch.setattr("api_client.api_get", lambda endpoint, params=None: [])
    monkeypatch.setattr(
        "api_client.api_post",
        lambda endpoint, payload, fail_on_error=True: posts.append(payload)
        or {"id": 42},
    )

    assert locations.get_or_create_location("Frankreich", locations_db=locations_db) == 42
    assert posts == [
        {
            "current_name": "Frankreich",
            "latitude": 46.0,
            "longitude": 2.0,
            "geonames_id": "3017382",
        }
    ]


def test_geonames_coordinates_fall_back_to_public_page(monkeypatch):
    class Response:
        def __init__(self, text="", error=None):
            self.text = text
            self.error = error

        def raise_for_status(self):
            if self.error:
                raise self.error

        def json(self):
            return {"status": {"value": 10}}

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "api.geonames.org" in url:
            return Response(error=locations.requests.RequestException("unauthorized"))
        return Response(
            text='{"@type":"GeoCoordinates","latitude":52.52437,"longitude":13.41053}'
        )

    monkeypatch.setattr(locations.requests, "get", fake_get)

    assert locations.extract_geonames_coordinates(
        "https://www.geonames.org/2950159/berlin.html"
    ) == {"lat": 52.52437, "long": 13.41053}
    assert calls == [
        "https://api.geonames.org/getJSON",
        "https://www.geonames.org/2950159/berlin.html",
    ]


def test_query_geocoder_parses_whereami_coordinate_response(monkeypatch):
    class Response:
        text = "50.59, 8.67"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(locations.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        locations.requests,
        "get",
        lambda url, **kwargs: Response(),
    )

    assert locations.query_geocoder("Gießen") == {"lat": 50.59, "long": 8.67}


def test_load_locations_falls_back_to_geonames_and_persists(tmp_path, monkeypatch):
    path = tmp_path / "locations.xlsx"
    write_locations(
        path,
        [
            "Gießen",
            "giessen",
            "",
            None,
            None,
            "",
            "https://www.geonames.org/2938913/giessen.html",
            "https://www.wikidata.org/wiki/Q2973",
            "",
        ],
    )
    locations._locations_db.clear()
    calls = []

    def geonames(url):
        calls.append("geonames")
        return {"lat": 50.59, "long": 8.67}

    monkeypatch.setattr(locations, "extract_geonames_coordinates", geonames)
    monkeypatch.setattr(
        locations,
        "extract_wikidata_coordinates",
        lambda url: (_ for _ in ()).throw(AssertionError("Wikidata should not run")),
    )

    database = locations.load_locations_db(path)

    entry = database[locations.normalize_location("Gießen")]
    assert (entry["lat"], entry["long"]) == (50.59, 8.67)
    assert calls == ["geonames"]
    assert read_coordinates(path) == (50.59, 8.67)


def test_load_locations_falls_back_to_wikidata_when_geonames_fails(tmp_path, monkeypatch):
    path = tmp_path / "locations.xlsx"
    write_locations(
        path,
        [
            "Kibbuz Ein HaNetziv",
            "ein hanetziv kibbuz",
            "",
            None,
            None,
            "",
            "https://www.geonames.org/295211/Ein-HaNaziv.html",
            "https://www.wikidata.org/wiki/Q2095906",
            "",
        ],
    )
    locations._locations_db.clear()
    calls = []

    monkeypatch.setattr(
        locations,
        "extract_geonames_coordinates",
        lambda url: calls.append("geonames") or None,
    )
    monkeypatch.setattr(
        locations,
        "extract_wikidata_coordinates",
        lambda url: calls.append("wikidata") or {"lat": 32.45, "long": 35.51},
    )

    database = locations.load_locations_db(path)

    entry = database[locations.normalize_location("Kibbuz Ein HaNetziv")]
    assert (entry["lat"], entry["long"]) == (32.45, 35.51)
    assert calls == ["geonames", "wikidata"]
    assert read_coordinates(path) == (32.45, 35.51)


def test_resolve_location_uses_name_geocoder_without_source_ids(monkeypatch):
    monkeypatch.setattr(
        locations,
        "query_geocoder",
        lambda name: {"lat": 50.59, "long": 8.67},
    )
    monkeypatch.setattr(
        locations,
        "extract_geonames_coordinates",
        lambda url: (_ for _ in ()).throw(AssertionError("no source ID fallback")),
    )
    monkeypatch.setattr(
        locations,
        "extract_wikidata_coordinates",
        lambda url: (_ for _ in ()).throw(AssertionError("no source ID fallback")),
    )

    entry = {"name": "Gießen"}
    assert locations.resolve_location_coordinates(entry) == (50.59, 8.67)
    assert (entry["lat"], entry["long"]) == (50.59, 8.67)


def test_resolve_location_does_not_name_geocode_when_source_id_exists(monkeypatch):
    called = []
    monkeypatch.setattr(locations, "extract_geonames_coordinates", lambda url: None)
    monkeypatch.setattr(locations, "extract_wikidata_coordinates", lambda url: None)
    monkeypatch.setattr(
        locations,
        "query_geocoder",
        lambda name: called.append(name) or {"lat": 50.59, "long": 8.67},
    )

    entry = {
        "name": "Gießen",
        "geonames_id": "2938913",
        "geonames_url": "https://www.geonames.org/2938913/giessen.html",
    }
    assert locations.resolve_location_coordinates(entry) is None
    assert called == []


def test_resolve_location_logs_failed_name_geocoder(monkeypatch, caplog):
    monkeypatch.setattr(locations, "query_geocoder", lambda name: None)

    with caplog.at_level("WARNING", logger="locations"):
        assert locations.resolve_location_coordinates({"name": "Unknown place"}) is None

    assert "Name geocoder returned no usable coordinates for Unknown place" in caplog.text


def test_coordinate_lookup_logs_failure_and_continues_to_next_source(monkeypatch, caplog):
    def failed_geonames(url):
        raise locations.requests.RequestException("GeoNames unavailable")

    monkeypatch.setattr(locations, "extract_geonames_coordinates", failed_geonames)
    monkeypatch.setattr(
        locations,
        "extract_wikidata_coordinates",
        lambda url: {"lat": 32.45, "long": 35.51},
    )

    with caplog.at_level("WARNING", logger="locations"):
        coordinates = locations.resolve_location_coordinates(
            {
                "name": "Kibbuz Ein HaNetziv",
                "geonames_url": "https://www.geonames.org/295211",
                "wikidata_url": "https://www.wikidata.org/wiki/Q2095906",
            }
        )

    assert coordinates == (32.45, 35.51)
    assert "GeoNames unavailable" in caplog.text


def test_location_api_failure_is_logged_and_returns_none(monkeypatch, caplog):
    locations._location_cache.clear()
    monkeypatch.setattr(
        "api_client.api_get",
        lambda endpoint, params=None: (_ for _ in ()).throw(
            locations.requests.RequestException("API unavailable")
        ),
    )

    with caplog.at_level("ERROR", logger="locations"):
        result = locations.get_or_create_location("Unavailable place")

    assert result is None
    assert "Location API lookup failed for Unavailable place" in caplog.text


def test_get_or_create_location_uses_normalized_db_key_and_repairs_existing_api_location(
    monkeypatch,
):
    locations._location_cache.clear()
    key = locations.normalize_location("Kibbuz Ein HaNetziv")
    locations_db = {
        key: {
            "name": "Kibbuz Ein HaNetziv",
            "lat": 32.45,
            "long": 35.51,
            "wikidata_id": "Q2095906",
            "geonames_id": "295211",
        }
    }
    patches = []
    monkeypatch.setattr(
        "api_client.api_get",
        lambda endpoint, params=None: [
            {"id": 7, "current_name": "Kibbuz Ein HaNetziv", "location": None}
        ],
    )
    monkeypatch.setattr(
        "api_client.api_patch",
        lambda endpoint, object_id, payload: patches.append(
            (endpoint, object_id, payload)
        ),
    )

    result = locations.get_or_create_location(
        "Kibbuz Ein HaNetziv", locations_db=locations_db
    )

    assert result == 7
    assert patches == [
        (
            "locations",
            7,
            {
                "latitude": 32.45,
                "longitude": 35.51,
                "wikidata_id": "Q2095906",
                "geonames_id": "295211",
            },
        )
    ]
