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