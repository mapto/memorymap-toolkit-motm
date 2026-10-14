"""Tests for merging metadata and chronotopi names into the Personae taxonomy."""

import json

import pytest
from openpyxl import Workbook

import person_taxonomy
import person_taxonomy.synonyms
from person_taxonomy import (
    PersonName,
    PersonTaxonomyError,
    augment_personae_taxonomy,
    canonical_person_name,
    load_person_taxonomy_synonyms,
    metadata_relative_name,
    person_taxonomy_alias,
    person_taxonomy_key,
)
from taxonomy import ROOT_KEY, Taxonomy
from taxonomy_import import import_taxonomy


def _write_metadata(
    path,
    *,
    given_name="Josef",
    family_name="Stern",
    relative_given_name="Johanna",
    relative_family_name="Kaminka",
):
    workbook = Workbook()
    person_sheet = workbook.active
    person_sheet.title = "Scheda individuale"
    person_sheet.append(["ID Sprecher", "P001"])
    person_sheet.append(["Vorname", given_name])
    person_sheet.append(["Nachname", family_name])

    family_sheet = workbook.create_sheet("Familie")
    family_sheet.append(["Family header"])
    family_sheet.append(["Column header"])
    family_sheet.append(["Template row"])
    family_sheet.append(
        [1, "Mutter", relative_given_name, relative_family_name, None, None, None]
    )
    workbook.save(path)


def test_person_synonym_mapping_covers_current_source_workbooks():
    synonyms = load_person_taxonomy_synonyms()
    metadata_by_chronotopi = synonyms.metadata_by_chronotopi

    assert metadata_by_chronotopi["chronotopoi_alsberg_reviewed.xlsx"] == (
        "metadati_Alsberg.xlsx"
    )
    assert metadata_by_chronotopi["chronotopoi_GILEAD.xlsx"] == "metadati_gilead.xlsx"
    assert metadata_by_chronotopi["chronotopoi_josef_stern_familie_v4a.xlsx"] == (
        "metadati_josef_stern_v4.xlsx"
    )
    assert synonyms.aliases[person_taxonomy_key("Johanna Stern")] == (
        "Kaminka, Johanna"
    )
    assert synonyms.aliases[person_taxonomy_key("Claire Stern")] == (
        "Thalheimer, Claire"
    )
    assert person_taxonomy_alias("Kaminka, Johanna") == "Kaminka, Johanna"
    assert person_taxonomy_alias("Johanna Kaminka") == "Kaminka, Johanna"


def test_metadata_and_sheet_names_create_a_surname_branch_and_aliases(tmp_path):
    data_root = tmp_path / "sources"
    data_root.mkdir()
    _write_metadata(data_root / "metadati_stern.xlsx")
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_stern.xlsx": "metadati_stern.xlsx"
                },
                "aliases": {
                    "Josef Stern": "Stern, Josef",
                    "Johanna Stern": "Kaminka, Johanna",
                },
            }
        ),
        encoding="utf-8",
    )
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["Personae"],
            "Personae": ["Burgheim, Hedwig"],
            "Burgheim, Hedwig": [],
        }
    )
    overview = {
        str(tmp_path / "chronotopi_stern.xlsx"): [
            "Josef Stern",
            "Johanna Stern",
            "_Vokabular",
        ]
    }

    augmentation = augment_personae_taxonomy(
        taxonomy,
        overview,
        data_root=data_root,
        synonyms_path=synonyms_path,
    )
    aliases = augmentation.aliases
    nodes = augmentation.taxonomy.concept_nodes()
    family = next(node for node in nodes if node.label == "Stern")
    josef = next(node for node in nodes if node.label == "Stern, Josef")
    johanna = next(node for node in nodes if node.label == "Kaminka, Johanna")

    assert josef.parent_key == family.key
    assert johanna.parent_key == family.key
    assert aliases[person_taxonomy_key("Josef Stern")] == "Stern, Josef"
    assert aliases[person_taxonomy_key("Johanna Stern")] == "Kaminka, Johanna"
    assert aliases[person_taxonomy_key("Hedwig Burgheim")] == "Burgheim, Hedwig"

    next_id = iter(range(1, 1000))
    imported = import_taxonomy(
        augmentation.taxonomy,
        lambda label, **kwargs: next(next_id),
        person_aliases=aliases,
    )
    assert imported.resolve_person("Josef Stern") == imported.resolve_person(
        "Stern, Josef"
    )
    assert imported.resolve_person("Johanna Stern") == imported.resolve_person(
        "Kaminka, Johanna"
    )


def test_missing_metadata_association_fails_before_taxonomy_import(tmp_path):
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Personae"], "Personae": []})

    try:
        augment_personae_taxonomy(
            taxonomy,
            {"chronotopi_unmapped.xlsx": ["Someone Example"]},
            data_root=tmp_path,
        )
    except ValueError as exc:
        assert "No metadata workbook is configured" in str(exc)
    else:
        raise AssertionError("unmapped chronotopi workbooks must fail clearly")


def test_existing_personae_leaf_is_nested_under_its_metadata_surname(tmp_path):
    data_root = tmp_path / "sources"
    data_root.mkdir()
    _write_metadata(data_root / "metadati_stern.xlsx")
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_stern.xlsx": "metadati_stern.xlsx"
                },
                "aliases": {"Josef Stern": "Stern, Josef"},
            }
        ),
        encoding="utf-8",
    )
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["Personae"],
            "Personae": ["Stern, Josef"],
            "Stern, Josef": [],
        }
    )

    augmentation = augment_personae_taxonomy(
        taxonomy,
        {"chronotopi_stern.xlsx": ["Josef Stern"]},
        data_root=data_root,
        synonyms_path=synonyms_path,
    )
    nodes = augmentation.taxonomy.concept_nodes()
    family = next(node for node in nodes if node.label == "Stern")
    josef = next(node for node in nodes if node.label == "Stern, Josef")

    assert josef.parent_key == family.key


def test_partial_overview_ignores_unreferenced_alias_targets(tmp_path):
    data_root = tmp_path / "sources"
    data_root.mkdir()
    _write_metadata(data_root / "metadati_stern.xlsx")
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_stern.xlsx": "metadati_stern.xlsx"
                },
                "aliases": {
                    "Josef Stern": "Stern, Josef",
                    "Unselected Person": "Missing Canonical Person",
                },
            }
        ),
        encoding="utf-8",
    )
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Personae"], "Personae": []})

    augmentation = augment_personae_taxonomy(
        taxonomy,
        {"chronotopi_stern.xlsx": ["Josef Stern"]},
        data_root=data_root,
        synonyms_path=synonyms_path,
    )

    assert "missing canonical person" not in {
        node.label.casefold() for node in augmentation.taxonomy.concept_nodes()
    }
    assert augmentation.aliases[person_taxonomy_key("Josef Stern")] == "Stern, Josef"


def test_people_are_grouped_by_source_file_not_name_spelling(tmp_path):
    data_root = tmp_path / "sources"
    data_root.mkdir()
    _write_metadata(
        data_root / "metadati_alsberg.xlsx",
        given_name="Paul Avraham",
        family_name="Alsberg",
        relative_given_name="Betti",
        relative_family_name="Keschner",
    )
    _write_metadata(data_root / "metadati_stern.xlsx")
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_alsberg.xlsx": "metadati_alsberg.xlsx",
                    "chronotopi_stern.xlsx": "metadati_stern.xlsx",
                },
                "aliases": {
                    "Paul Avraham Alsberg": "Alsberg, Paul Avraham",
                    "Betti Keschner": "Keschner, Betti",
                    "Josef Stern": "Stern, Josef",
                    "Johanna Stern": "Kaminka, Johanna",
                },
            }
        ),
        encoding="utf-8",
    )
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Personae"], "Personae": []})
    overview = {
        "chronotopi_alsberg.xlsx": ["Paul Avraham Alsberg", "Betti Keschner"],
        "chronotopi_stern.xlsx": ["Josef Stern", "Johanna Stern"],
    }

    augmentation = augment_personae_taxonomy(
        taxonomy,
        overview,
        data_root=data_root,
        synonyms_path=synonyms_path,
    )
    aliases = augmentation.aliases
    nodes = augmentation.taxonomy.concept_nodes()
    by_label = {node.label: node for node in nodes}
    alsberg = by_label["Alsberg"]
    stern = by_label["Stern"]

    assert by_label["Keschner, Betti"].parent_key == alsberg.key
    assert by_label["Kaminka, Johanna"].parent_key == stern.key
    assert by_label["Stern, Josef"].parent_key == stern.key
    assert aliases[person_taxonomy_key("Johanna Stern")] == "Kaminka, Johanna"

    nodes_by_key = {node.key: node for node in nodes}
    for workbook_name, expected_family, sheet_names in (
        ("chronotopi_alsberg.xlsx", "Alsberg", overview["chronotopi_alsberg.xlsx"]),
        ("chronotopi_stern.xlsx", "Stern", overview["chronotopi_stern.xlsx"]),
    ):
        for sheet_name in sheet_names:
            canonical = aliases[person_taxonomy_key(sheet_name)]
            person_node = by_label[canonical]
            assert nodes_by_key[person_node.parent_key].label == expected_family, (
                workbook_name,
                sheet_name,
            )


def test_unnamed_metadata_relatives_do_not_create_placeholder_leaves(tmp_path):
    data_root = tmp_path / "sources"
    data_root.mkdir()
    _write_metadata(
        data_root / "metadati_stern.xlsx",
        relative_given_name="unbekannt",
        relative_family_name="Guttfeld",
    )
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_by_chronotopi": {
                    "chronotopi_stern.xlsx": "metadati_stern.xlsx"
                },
                "aliases": {"Josef Stern": "Stern, Josef"},
            }
        ),
        encoding="utf-8",
    )
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Personae"], "Personae": []})

    augmentation = augment_personae_taxonomy(
        taxonomy,
        {"chronotopi_stern.xlsx": ["Josef Stern"]},
        data_root=data_root,
        synonyms_path=synonyms_path,
    )
    labels = {node.label for node in augmentation.taxonomy.concept_nodes()}

    assert "Stern, Josef" in labels
    assert not any("unbekannt" in label.casefold() for label in labels)
    assert not any("unbekannt" in key for key in augmentation.aliases)


def test_brodsky_metadata_relatives_link_to_reviewed_aunts():
    tante_1 = "Tante 1 (Schwester der Mutter)"
    tante_2 = "Tante 2 (Schwester der Mutter)"

    assert metadata_relative_name("metadati_brodsky.xlsx", tante_1) == PersonName(
        family_name="Brodsky", given_name="Tante 1"
    )
    assert metadata_relative_name("metadati_brodsky.xlsx", tante_2) == PersonName(
        family_name="Nelken", given_name="Frau Doktor"
    )


def test_metadata_relative_links_are_scoped_to_their_workbook(tmp_path, monkeypatch):
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "metadata_relatives": {
                    "metadati_brodsky.xlsx": {
                        "Tante 1 (Schwester der Mutter)": "Brodsky, Tante 1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        person_taxonomy.synonyms, "PERSON_TAXONOMY_SYNONYMS_PATH", synonyms_path
    )
    relation = "Tante 1 (Schwester der Mutter)"

    assert metadata_relative_name(tmp_path / "metadati_brodsky.xlsx", relation) == (
        PersonName(family_name="Brodsky", given_name="Tante 1")
    )
    assert metadata_relative_name("metadati_other.xlsx", relation) is None
    assert metadata_relative_name(None, relation) is None


def test_metadata_relative_targets_must_be_surname_given_labels(tmp_path):
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {"metadata_relatives": {"metadati_brodsky.xlsx": {"Tante 1": "Tante 1"}}}
        ),
        encoding="utf-8",
    )

    with pytest.raises(PersonTaxonomyError, match="Surname, Given"):
        load_person_taxonomy_synonyms(synonyms_path)


def test_person_name_parses_surname_given_labels():
    name = PersonName.from_label("  Stern ,  Josef ")

    assert name == PersonName(family_name="Stern", given_name="Josef")
    assert name.label == "Stern, Josef"
    assert name.natural_order == "Josef Stern"
    assert name.variants() == ["Josef Stern", "Stern, Josef"]
    assert PersonName.from_label("Tante 1") is None


def test_loaded_person_synonyms_are_read_only(tmp_path):
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps({"aliases": {"Josef Stern": "Stern, Josef"}}), encoding="utf-8"
    )

    synonyms = load_person_taxonomy_synonyms(synonyms_path)

    assert synonyms.aliases[person_taxonomy_key("Josef Stern")] == "Stern, Josef"
    with pytest.raises(TypeError):
        synonyms.aliases["new name"] = "New, Name"
    with pytest.raises(TypeError):
        synonyms.metadata_by_chronotopi["chronotopi_new.xlsx"] = "metadati_new.xlsx"


def test_canonical_person_name_returns_none_when_unmapped(tmp_path, monkeypatch):
    synonyms_path = tmp_path / "person_synonyms.json"
    synonyms_path.write_text(
        json.dumps({"aliases": {"Josef Stern": "Stern, Josef"}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        person_taxonomy.synonyms, "PERSON_TAXONOMY_SYNONYMS_PATH", synonyms_path
    )

    assert canonical_person_name("Josef", "Stern") == PersonName(
        family_name="Stern", given_name="Josef"
    )
    assert canonical_person_name("Nobody", "Unknown") is None
