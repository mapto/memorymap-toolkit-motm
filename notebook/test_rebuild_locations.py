"""Tests for rebuilding the location workbook from source evidence."""

from pathlib import Path

import openpyxl

import rebuild_locations


def test_resolve_coordinates_prefers_chronotopi_direct_coordinates(monkeypatch):
    source = rebuild_locations.SourceLocation(
        name="Berlin",
        direct_coordinates=[(52.5, 13.4)],
        geonames_ids={"2950159"},
    )
    monkeypatch.setattr(
        rebuild_locations,
        "extract_geonames_coordinates",
        lambda url: (_ for _ in ()).throw(AssertionError("GeoNames must not run")),
    )

    coordinates, source_name, address = rebuild_locations.resolve_coordinates(
        "Berlin",
        {},
        source,
        own_geocoder=lambda query: (_ for _ in ()).throw(
            AssertionError("own geocoder must not run")
        ),
        nominatim=lambda query: (_ for _ in ()).throw(
            AssertionError("Nominatim must not run")
        ),
    )

    assert coordinates == (52.5, 13.4)
    assert source_name == "chronotopi"
    assert address == {}


def test_resolve_coordinates_falls_through_to_geonames_then_wikidata(monkeypatch):
    source = rebuild_locations.SourceLocation(name="Berlin", geonames_ids={"2950159"})
    monkeypatch.setattr(
        rebuild_locations,
        "extract_geonames_coordinates",
        lambda url: {"lat": 52.5, "long": 13.4},
    )

    coordinates, source_name, _ = rebuild_locations.resolve_coordinates(
        "Berlin",
        {},
        source,
        own_geocoder=lambda query: None,
        nominatim=lambda query: None,
    )

    assert coordinates == (52.5, 13.4)
    assert source_name == "geonames"


def test_resolve_coordinates_uses_own_geocoder_before_nominatim():
    calls = []

    coordinates, source_name, _ = rebuild_locations.resolve_coordinates(
        "Unknown",
        {},
        rebuild_locations.SourceLocation(name="Unknown"),
        own_geocoder=lambda query: (
            calls.append(("own", query)) or {"lat": 50.6, "long": 8.7}
        ),
        nominatim=lambda query: calls.append(("nominatim", query)) or None,
    )

    assert coordinates == (50.6, 8.7)
    assert source_name == "own-geocoder"
    assert calls == [("own", "Unknown")]


def test_wider_region_uses_taxonomy_path_and_context():
    geo_paths = {
        "deutschland": (
            "GO – geographischer Ort",
            "Deutschland",
        ),
        "berlin": (
            "GO – geographischer Ort",
            "Deutschland",
            "Berlin",
        ),
        "giessen": (
            "GO – geographischer Ort",
            "Deutschland",
            "Gießen",
        ),
    }

    assert (
        rebuild_locations.wider_region_for("Berlin", {}, None, geo_paths, {})
        == "GO – geographischer Ort > Deutschland"
    )
    assert (
        rebuild_locations.wider_region_for(
            "Steinstraße 19",
            {},
            rebuild_locations.SourceLocation(name="Steinstraße 19", details={"Gießen"}),
            geo_paths,
            {},
        )
        == "GO – geographischer Ort > Deutschland > Gießen"
    )
    assert (
        rebuild_locations.wider_region_for(
            "Sennfeld (Adelsheim)", {}, None, geo_paths, {}
        )
        == "GO – geographischer Ort > Deutschland"
    )


def test_latinize_text_transliterates_non_latin_region_labels():
    value = rebuild_locations.latinize_text("ירושלים | القدس")

    assert value.isascii()
    assert value


def test_reviewed_taxonomy_synonyms_resolve_to_canonical_labels():
    assert rebuild_locations.taxonomy_alias("Frankfurt/M") == "Frankfurt am Main"
    assert rebuild_locations.taxonomy_alias("Israel") == "Palästina – Israel"
    assert rebuild_locations.taxonomy_match_excluded("Koblenz") is True


def test_order_output_headers_places_derived_columns_after_super_region():
    headers = ["location", "lat", "super_region", "label", "wider_region"]

    assert rebuild_locations.order_output_headers(headers) == [
        "location",
        "lat",
        "super_region",
        "wider_region",
        "coordinate_source",
        "label",
    ]


def test_location_key_merges_address_name_variants():
    assert rebuild_locations.location_key(
        "Ghettohaus, Walltorstraße 48"
    ) == rebuild_locations.location_key("Walltorstraße 48")


def test_read_metadata_sources_collects_birth_place_evidence(monkeypatch, tmp_path):
    workbook = tmp_path / "metadati_test.xlsx"
    workbook.touch()
    import metadati

    monkeypatch.setattr(
        metadati,
        "read_person_record",
        lambda path: {
            "birth_place": {
                "name": "Wien",
                "coordinates": {"lat": 48.2, "lon": 16.3},
                "wikidata_id": "Q174",
                "regions": ["Österreich"],
            }
        },
    )

    sources = rebuild_locations.read_metadata_sources(tmp_path)

    source = sources[rebuild_locations.location_key("Wien")]
    assert source.direct_coordinates == [(48.2, 16.3)]
    assert source.wikidata_ids == {"Q174"}
    assert source.details == {"Österreich"}
    assert rebuild_locations.location_key(
        "Marktplatz 11, Giessen"
    ) == rebuild_locations.location_key("Marktplatz 11")


def test_rebuild_preserves_columns_and_adds_provenance_columns(tmp_path, monkeypatch):
    input_path = tmp_path / "locations.xlsx"
    output_path = tmp_path / "rebuilt.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["location", "bag_of_words", "super_region", "lat", "long", "label"])
    sheet.append(["Berlin", "", "", "", "", ""])
    workbook.save(input_path)

    monkeypatch.setattr(
        rebuild_locations,
        "read_chronotopi_sources",
        lambda root: {
            "berlin": rebuild_locations.SourceLocation(
                name="Berlin", direct_coordinates=[(52.5, 13.4)]
            )
        },
    )
    monkeypatch.setattr(rebuild_locations, "read_metadata_sources", lambda root: {})
    monkeypatch.setattr(
        rebuild_locations,
        "load_taxonomy",
        lambda path: type("TaxonomyStub", (), {"occurrences": ()})(),
    )

    result = rebuild_locations.rebuild_workbook(
        input_path=input_path,
        output_path=output_path,
        data_root=Path("."),
        taxonomy_path=Path("taxonomy.mmd"),
        own_geocoder=lambda query: None,
        nominatim=lambda query: None,
    )

    rebuilt = openpyxl.load_workbook(output_path, read_only=True, data_only=True).active
    headers = [cell.value for cell in rebuilt[1]]
    row = [cell.value for cell in rebuilt[2]]
    assert result["rows"] == 1
    assert headers[:7] == [
        "location",
        "bag_of_words",
        "super_region",
        "wider_region",
        "coordinate_source",
        "lat",
        "long",
    ]
    assert row[headers.index("lat")] == 52.5
    assert row[headers.index("long")] == 13.4
    assert row[headers.index("coordinate_source")] == "chronotopi"
    assert row[headers.index("super_region")].isascii()
