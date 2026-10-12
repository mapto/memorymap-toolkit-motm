"""Unit tests for metadata workbook parsing and pure helpers."""

import pytest
from openpyxl import Workbook

import metadati


def test_clean_value_returns_none_for_empty_values():
    assert metadati.clean_value(None) is None
    assert metadati.clean_value("  ") is None
    assert metadati.clean_value("value") == "value"


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("Stern, Josef", ("Josef", "Stern")),
        ("Josef Stern", ("Josef", "Stern")),
        ("Josef", ("Josef", "UNKNOWN")),
    ],
)
def test_parse_name(full_name, expected):
    assert metadati.parse_name(full_name) == expected


@pytest.mark.parametrize(
    "source_label",
    [
        "Anne Betten, IS_E_00124",
        "Anne Betten + IS_E_00124",
    ],
)
def test_parse_source_label_extracts_interviewer_and_corpus_id(source_label):
    assert metadati.parse_source_label(source_label) == (
        "Anne Betten",
        "IS_E_00124",
    )


def test_read_person_record_starts_family_rows_at_row_four(tmp_path):
    workbook = Workbook()
    person_sheet = workbook.active
    person_sheet.title = "Scheda individuale"
    person_sheet.append(["Metadaten - P001"])
    person_sheet.append(["ID Sprecher", "P001"])
    person_sheet.append(["Vorname", "Josef"])
    person_sheet.append(["Nachname", "Stern"])

    family_sheet = workbook.create_sheet("Familie")
    family_sheet.append(["Family header"])
    family_sheet.append(["Column header"])
    family_sheet.append(["This row is not a family member", "Header"])
    family_sheet.append(
        [
            1,
            "Mutter",
            "Maria",
            "Stern",
            "12.03.1920",
            "Berlin",
            "Family note",
        ]
    )

    workbook_path = tmp_path / "metadati_P001.xlsx"
    workbook.save(workbook_path)

    record = metadati.read_person_record(workbook_path)

    assert record["identifier"] == "P001"
    assert record["person"]["given_name"] == "Josef"
    assert record["family"] == [
        {
            "relation": "Mutter",
            "given_name": "Maria",
            "family_name": "Stern",
            "birth_date": "1920-03-12",
            "death_date": None,
            "birth_place": "Berlin",
            "notes": "Family note",
        }
    ]


def test_read_person_record_skips_empty_family_rows(tmp_path):
    workbook = Workbook()
    person_sheet = workbook.active
    person_sheet.title = "Scheda individuale"
    family_sheet = workbook.create_sheet("Familie")
    family_sheet.append(["Family header"])
    family_sheet.append(["Column header"])
    family_sheet.append(["Template row"])
    family_sheet.append([None] * 7)
    family_sheet.append([1, "Bruder", "Hans", "Stern", None, None, None])

    workbook_path = tmp_path / "metadati_P002.xlsx"
    workbook.save(workbook_path)

    record = metadati.read_person_record(workbook_path)

    assert len(record["family"]) == 1
    assert record["family"][0]["relation"] == "Bruder"


def test_create_interview_uses_shared_normalized_upsert(monkeypatch):
    calls = []
    monkeypatch.setattr(
        metadati,
        "get_or_create_person",
        lambda data: 8,
    )

    def fake_upsert(payloads):
        calls.extend(payloads)
        return {"IS_E_00170": 17}, []

    monkeypatch.setattr(metadati, "upsert_interviews", fake_upsert)
    monkeypatch.setattr(metadati, "get_or_create_url", lambda value: 31)

    interview_id = metadati.create_interview(
        7,
        {
            "archive_id": "IS_E_170",
            "type": "Interview (oral)",
            "date": "08.05.1991",
            "place": "Berlin",
            "interviewer": "Doe, Jane",
            "url": "https://example.test/interview/1",
        },
    )

    assert interview_id == 17
    assert calls == [
        {
            "archive_id": "IS_E_00170",
            "interviewee": 7,
            "interviewer": 8,
            "interview_type": "oral",
            "date": "1991-05-08",
            "place": "Berlin",
            "urls": [31],
        }
    ]


def test_read_person_record_extracts_source_url(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scheda individuale"
    sheet.append(["ID Sprecher", "P001"])
    sheet.append(["Quelle 1", None])
    sheet.append(["Quelle 1 – Bezeichnung", "Anne Betten, IS_E_00124"])
    sheet.append(["Quelle 1 – Ort", "Jerusalem"])
    sheet.append(["Quelle 1 – Handle/URL", "https://example.test/interview/1"])

    workbook_path = tmp_path / "metadati_P001.xlsx"
    workbook.save(workbook_path)

    record = metadati.read_person_record(workbook_path)

    assert record["interviews"] == [
        {
            "type": None,
            "place": "Jerusalem",
            "date": None,
            "interviewer": "Anne Betten",
            "archive_id": "IS_E_00124",
            "url": "https://example.test/interview/1",
        }
    ]


def test_read_person_record_extracts_place_metadata(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scheda individuale"
    sheet.append([
        "Geburtsort",
        "Frankfurt an der Oder\nLand: Deutsches Reich | "
        "Geokoordinaten (Breite/Länge): [52.35 / 14.55] | "
        "Ortsname: Frankfurt an der Oder",
    ])

    workbook_path = tmp_path / "metadati_place.xlsx"
    workbook.save(workbook_path)

    record = metadati.read_person_record(workbook_path)

    assert record["birth_place"] == {
        "name": "Frankfurt an der Oder",
        "coordinates": {"lat": 52.35, "lon": 14.55},
        "wikidata_id": None,
        "regions": ["Deutsches Reich"],
    }


def test_read_person_record_extracts_person_metadata(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scheda individuale"
    sheet.append(["Schulbildung / Abschluss", "Gymnasium\nmit Abschluss"])
    sheet.append(["Beruf (zum Zeitpunkt der Emigration)", "Schüler"])
    sheet.append(["Beruf (zum Zeitpunkt der Quelle)", "Bibliothekar; Historiker"])
    sheet.append(["Wohnort zum Zeitpunkt der Quelle", "Haifa"])

    workbook_path = tmp_path / "metadati_metadata.xlsx"
    workbook.save(workbook_path)

    record = metadati.read_person_record(workbook_path)

    assert record["person"] == {
        "given_name": None,
        "previous_given_name": None,
        "family_name": None,
        "previous_family_name": None,
        "gender": None,
        "birth_date": None,
        "education": "Gymnasium mit Abschluss",
        "occupation_at_emigration": "Schüler",
        "occupation_at_source": "Bibliothekar; Historiker",
        "residence_at_source": "Haifa",
        "attributes": {},
    }


def test_create_interview_skips_missing_archive_id(monkeypatch):
    monkeypatch.setattr(
        metadati,
        "upsert_interviews",
        lambda payloads: pytest.fail("should not upsert without archive ID"),
    )

    assert metadati.create_interview(7, {"archive_id": None}) is None
