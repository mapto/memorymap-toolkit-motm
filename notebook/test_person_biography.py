"""Tests for chronotopi biography extraction, source validation, and API writes."""

import json
from datetime import date

import pandas as pd
import pytest
from openpyxl import Workbook

import person_biography as biography
from timespan import Timespan, parse_timespan


def _write_sources(tmp_path, *, main_birth="1924", main_place="Frankfurt an der Oder"):
    metadata_path = tmp_path / "metadati_test.xlsx"
    workbook = Workbook()
    person_sheet = workbook.active
    person_sheet.title = "Scheda individuale"
    person_sheet.append(["ID Sprecher", "P001"])
    person_sheet.append(["Vorname", "Ada"])
    person_sheet.append(["Nachname", "Subject"])
    person_sheet.append(["Geburtsdatum", main_birth])
    person_sheet.append(["Geburtsort", main_place])

    family_sheet = workbook.create_sheet("Familie")
    family_sheet.append(["Family"])
    family_sheet.append([None])
    family_sheet.append(
        [
            "ID_Sprecher",
            "Beziehung",
            "Vorname",
            "Nachname (geb.)",
            "Geburtsdatum",
            "Geburtsort",
            "Anmerkungen",
        ]
    )
    family_sheet.append(
        ["P001", "Mutter", "Johanna", "Kaminka", "17.5.1896–1923", "Lollar", ""]
    )
    family_sheet.append(
        [
            "P001",
            "Großmutter",
            "Auguste",
            "Rossmann",
            "22.5.1862–1942",
            "Wölfersheim",
            "",
        ]
    )
    workbook.save(metadata_path)

    synonyms_path = tmp_path / "person_taxonomy_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_test.xlsx": "metadati_test.xlsx"
                },
                "aliases": {
                    "Johanna Stern": "Kaminka, Johanna",
                    "Auguste Stern": "Rossmann, Auguste",
                },
            }
        ),
        encoding="utf-8",
    )

    rows = [
        {
            "name": "Ada Subject",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Geburt",
            "event_type": "birth",
            "date_start": "1924-10-30",
            "date_end": "1924-10-30",
            "date_label": "30.10.1924",
            "place_name": "Frankfurt an der Oder",
            "place_detail": "Altstadt 3",
        },
        {
            "name": "Ada Subject",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Tod des Vaters",
            "event_type": "other (biographisch bedeutungsvolle Beziehungen)",
            "date_start": "1947-02-19",
            "date_end": "1947-02-19",
            "date_label": "19.02.1947",
            "place_name": "Tel Aviv",
        },
        {
            "name": "Johanna Stern",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Geburt",
            "event_type": "birth",
            "date_start": "1896-05-17",
            "date_end": "1896-05-17",
            "date_label": "17.5.1896",
            "place_name": "Lollar",
        },
        {
            "name": "Johanna Stern",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Tod",
            "event_type": "death",
            "date_start": "1923",
            "date_end": "1923",
            "date_label": "1923",
            "place_name": "Gießen",
        },
        {
            "name": "Auguste Stern",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Geburt",
            "event_type": "birth",
            "date_start": "1862-05-22",
            "date_end": "1862-05-22",
            "date_label": "22/05/1862",
            "place_name": "Wölfersheim",
        },
        {
            "name": "Auguste Stern",
            "source_workbook": "chronotopi_test.xlsx",
            "event_label": "Tod/Ermordung",
            "event_type": "murder",
            "date_start": "1942-09-26",
            "date_end": "1942-09-26",
            "date_label": "26/09/1942",
            "place_name": "Theresienstadt",
        },
    ]
    dataframe = pd.DataFrame(rows)
    overview = {"chronotopi_test.xlsx": ["Ada Subject", "Johanna Stern", "Auguste Stern"]}
    return dataframe, overview, synonyms_path


def _build_plan(tmp_path, **source_options):
    dataframe, overview, synonyms_path = _write_sources(tmp_path, **source_options)
    return biography.build_person_biography_plan(
        overview,
        dataframe,
        tmp_path,
        synonyms_path=synonyms_path,
    )


def _find_biography(plan, name):
    return next(item for item in plan.values() if item.person_name == name)


def test_build_plan_reconciles_main_and_family_metadata_at_available_precision(tmp_path):
    plan = _build_plan(tmp_path)

    ada = _find_biography(plan, "Ada Subject")
    assert ada.birth_date == "1924-10-30"
    assert ada.birth_place == "Frankfurt an der Oder (Altstadt 3)"
    assert ada.death_span is None

    johanna = _find_biography(plan, "Johanna Stern")
    assert johanna.birth_date == "1896-05-17"
    assert johanna.birth_place == "Lollar"
    assert johanna.death_span == Timespan(
        date(1923, 1, 1), date(1923, 12, 31), is_point=False
    )
    assert johanna.death_place == "Gießen"

    auguste = _find_biography(plan, "Auguste Stern")
    assert auguste.birth_date == "1862-05-22"
    assert auguste.death_date == "1942-09-26"
    assert auguste.death_place == "Theresienstadt"


def test_relative_death_event_is_not_assigned_to_the_sheet_protagonist():
    assert biography._classify_biographical_event(
        {"event_label": "Tod des Vaters", "event_type": "death"}
    ) is None
    assert biography._classify_biographical_event(
        {"event_label": "Geburtshaus Marktplatz 11", "event_type": "return_visit_transit"}
    ) is None


def test_murder_event_type_is_a_death_event():
    assert biography._classify_biographical_event(
        {"event_label": "Tod/Ermordung", "event_type": "murder"}
    ) == "death"


@pytest.mark.parametrize(
    ("date_label", "expected_end"),
    [
        ("1951", date(1951, 12, 31)),
        ("Januar 1934", date(1934, 1, 31)),
        ("01.01.1934", date(1934, 1, 1)),
    ],
)
def test_event_date_columns_retain_partial_precision_from_date_label(
    date_label, expected_end
):
    parsed = biography._event_date_span(
        {
            "date_start": "1951-01-01" if date_label == "1951" else "1934-01-01",
            "date_end": "1951-01-01" if date_label == "1951" else "1934-01-01",
            "date_label": date_label,
        }
    )

    assert parsed.end == expected_end


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("Sennfeld", "Sennfeld (Adelsheim)", True),
        ("Posen", "Posen/Poznan", True),
        ("Gießen", "Giessen", True),
        ("Gießen", "Jerusalem", False),
    ],
)
def test_place_comparison_normalizes_known_variants(left, right, expected):
    assert biography.place_names_equivalent(left, right) is expected


@pytest.mark.parametrize(
    ("main_birth", "main_place", "field"),
    [
        ("1923", "Frankfurt an der Oder", "date"),
        ("1924", "Berlin", "place"),
    ],
)
def test_source_preflight_reports_metadata_conflicts(
    tmp_path, main_birth, main_place, field
):
    with pytest.raises(biography.PersonBiographyConflictError) as error:
        _build_plan(tmp_path, main_birth=main_birth, main_place=main_place)

    assert "Ada Subject" in str(error.value)
    assert f"{field}" in str(error.value)


def test_parse_span_handles_chronotopi_excel_date_spellings():
    assert _span_label(parse_timespan("1924.10.30")) == "1924-10-30"
    assert _span_label(parse_timespan("03.Juli 1880")) == "1880-07-03"
    assert _span_label(parse_timespan("1974.0")) == (
        "1974-01-01 through 1974-12-31"
    )


def _span_label(span):
    if span.start == span.end:
        return span.start.isoformat()
    return f"{span.start.isoformat()} through {span.end.isoformat()}"


def test_api_import_sets_lifespan_and_birth_and_death_places(monkeypatch):
    biography_plan = {
        "ada subject": biography.PersonBiography(
            person_name="Ada Subject",
            identity_key="ada subject",
            birth_span=Timespan(date(1924, 10, 30)),
            birth_place="Frankfurt an der Oder",
            death_span=Timespan(date(2011, 4, 12)),
            death_place="Jerusalem",
        )
    }
    patches = []
    monkeypatch.setattr(biography, "get_person_id", lambda *_: 7)
    monkeypatch.setattr(
        biography,
        "api_get",
        lambda endpoint: {"id": 7, "lifespan": None}
        if endpoint == "persons/7"
        else {},
    )
    monkeypatch.setattr(
        biography,
        "get_or_create_timespan",
        lambda start, end: ("timespan", start, end),
    )
    monkeypatch.setattr(
        biography,
        "get_or_create_location",
        lambda place, **kwargs: f"location:{place}",
    )
    monkeypatch.setattr(
        biography,
        "api_patch",
        lambda endpoint, obj_id, payload: patches.append((endpoint, obj_id, payload)),
    )

    result = biography.import_person_biographies(biography_plan)

    assert result == [7]
    assert patches == [
        (
            "persons",
            7,
            {
                "lifespan": ("timespan", "1924-10-30", "2011-04-12"),
                "birth_place": "location:Frankfurt an der Oder",
                "death_place": "location:Jerusalem",
            },
        )
    ]


def test_existing_person_conflict_is_rejected_before_patch(monkeypatch):
    plan = {
        "ada subject": biography.PersonBiography(
            person_name="Ada Subject",
            identity_key="ada subject",
            birth_span=Timespan(date(1924, 10, 30)),
        )
    }
    monkeypatch.setattr(
        biography,
        "api_get",
        lambda endpoint: (
            [{"id": 7, "given_name": "Ada", "family_name": "Subject", "lifespan": 3}]
            if endpoint == "persons"
            else [{"id": 3, "start": "1923-01-01", "end": None}]
            if endpoint == "timespans"
            else {}
        ),
    )
    monkeypatch.setattr(
        biography,
        "api_patch",
        lambda *args: pytest.fail("preflight must not write"),
    )

    with pytest.raises(biography.PersonBiographyConflictError, match="birth date"):
        biography.validate_existing_person_biographies(plan)