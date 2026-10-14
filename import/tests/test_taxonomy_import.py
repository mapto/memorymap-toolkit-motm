"""Tests for importing taxonomy nodes into parent-linked concept records."""

from taxonomy import ROOT_KEY, Taxonomy
from taxonomy_import import import_taxonomy


def test_import_taxonomy_creates_parent_first_and_keeps_cross_category_labels():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: [
                "GO – geographischer Ort",
                "Zeitangaben",
                "Personae",
                "LL – Lebenslauf",
                "SR – soziale Räume",
                "VM – Verkehr & Bewegungsräume",
                "Sprache(n)",
                "alte Heimat",
            ],
            "GO – geographischer Ort": ["Shared", "Berlin"],
            "Zeitangaben": ["Shared", "1933"],
            "Personae": ["Ada"],
            "LL – Lebenslauf": ["Geburt", "Tod", "Beruf"],
            "SR – soziale Räume": ["Wohnung / Wohnort"],
            "VM – Verkehr & Bewegungsräume": ["Zug", "Schiff"],
            "Sprache(n)": ["Englisch"],
            "alte Heimat": [],
            "Shared": [],
            "Berlin": [],
            "1933": [],
            "Ada": [],
            "Geburt": [],
            "Tod": [],
            "Beruf": [],
            "Wohnung / Wohnort": [],
            "Zug": [],
            "Schiff": [],
            "Englisch": [],
        }
    )
    calls = []

    def create_concept(label, parent_id=None, icon=None, identity=None):
        concept_id = len(calls) + 1
        calls.append((concept_id, label, parent_id, icon, identity))
        return concept_id

    imported = import_taxonomy(taxonomy, create_concept)

    go_root_id = imported.resolve_location("GO – geographischer Ort")
    berlin_id = imported.resolve_location("Berlin")
    shared_ids = [
        imported.ids_by_key[node.key]
        for node in imported.nodes_by_key.values()
        if node.label == "Shared"
    ]

    assert go_root_id is not None
    assert berlin_id is not None
    assert calls[0][2] is None
    assert calls[1][2] == go_root_id
    assert calls[1][1] == "Shared"
    assert imported.resolve_time_period("1933") is not None
    assert imported.resolve_person("Ada") is not None
    assert imported.resolve_concept("birth") == imported.resolve_concept("Geburt")
    assert imported.resolve_concept("alte_heimat") == imported.resolve_concept(
        "alte Heimat"
    )
    assert len(shared_ids) == 2
    assert shared_ids[0] != shared_ids[1]


def test_import_taxonomy_returns_none_for_unknown_source_labels():
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Root"], "Root": []})
    next_id = iter(range(1, 20))
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: next(next_id))

    assert imported.resolve_concept("not in taxonomy") is None


def test_resolve_person_uses_reviewed_person_aliases():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["Personae"],
            "Personae": ["Stern"],
            "Stern": ["Stern, Josef"],
            "Stern, Josef": [],
        }
    )
    next_id = iter(range(1, 20))
    imported = import_taxonomy(
        taxonomy,
        lambda label, **kwargs: next(next_id),
        person_aliases={"Josef Stern": "Stern, Josef"},
    )

    assert imported.resolve_person("Josef Stern") == imported.resolve_person(
        "Stern, Josef"
    )
    assert imported.resolve_person("unknown person") is None


def test_person_alias_targets_must_exist_under_personae():
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Personae"], "Personae": []})
    calls = []

    try:
        import_taxonomy(
            taxonomy,
            lambda label, **kwargs: calls.append(label) or len(calls),
            person_aliases={"Unknown Person": "Missing Person"},
        )
    except ValueError as exc:
        assert "not in the Personae taxonomy" in str(exc)
    else:
        raise AssertionError("aliases with unknown canonical targets must be rejected")

    assert calls == []


def test_person_alias_targets_must_be_leaves():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["Personae"],
            "Personae": ["Stern"],
            "Stern": ["Stern, Josef"],
            "Stern, Josef": [],
        }
    )
    calls = []

    try:
        import_taxonomy(
            taxonomy,
            lambda label, **kwargs: calls.append(label) or len(calls),
            person_aliases={"Stern family": "Stern"},
        )
    except ValueError as exc:
        assert "is not a Personae leaf" in str(exc)
    else:
        raise AssertionError("aliases must not resolve to a family branch")

    assert calls == []


def test_resolve_location_matches_synonyms_embedded_labels_and_exclusions():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": ["Deutschland", "Palästina – Israel"],
            "Deutschland": ["Gießen", "Buchenwald"],
            "Palästina – Israel": ["Jerusalem"],
            "Gießen": [],
            "Buchenwald": [],
            "Jerusalem": [],
        }
    )
    calls = []
    imported = import_taxonomy(
        taxonomy,
        lambda label, **kwargs: calls.append((label, kwargs)) or len(calls),
    )

    assert imported.resolve_location(
        "Gießen Marktplatz 15"
    ) == imported.resolve_location("Gießen")
    assert imported.resolve_location(
        "KZ Buchenwald (Buchenwald)"
    ) == imported.resolve_location("Buchenwald")
    yad_vashem_id = imported.ensure_location_concept("Yad Vashem")
    assert yad_vashem_id is not None
    assert imported.resolve_location_exact("Yad Vashem") == yad_vashem_id
    assert (
        imported.ids_by_key[
            imported.nodes_by_key[("go", "supplemental", "yad vashem")].key
        ]
        == yad_vashem_id
    )
    assert imported.resolve_location("Koblenz") is None
    assert (
        imported.resolve_location(
            "Gießen Marktplatz 15",
            allow_aliases=False,
            allow_embedded=False,
        )
        is None
    )


def test_location_aliases_normalize_case_dashes_and_underscores():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": ["Deutschland"],
            "Deutschland": ["Frankfurt am Main", "Kehl"],
            "Frankfurt am Main": [],
            "Kehl": [],
        }
    )
    next_id = iter(range(1, 20))
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: next(next_id))
    frankfurt_id = imported.resolve_location_exact("Frankfurt am Main")
    kehl_id = imported.resolve_location_exact("Kehl")

    assert imported.resolve_location_exact("Frankfurt_Main") == frankfurt_id
    assert imported.resolve_location_exact("FRANKFURT-MAIN") == frankfurt_id
    assert imported.resolve_location_exact("Kehl am Rhein") == kehl_id
    assert imported.ensure_location_concept("Koblenz") is None


def test_detailed_address_alias_resolves_to_address_not_city():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": ["Deutschland"],
            "Deutschland": ["Gießen"],
            "Gießen": ["Marktplatz 11"],
            "Marktplatz 11": [],
        }
    )
    next_id = iter(range(1, 20))
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: next(next_id))

    assert imported.resolve_location_exact("Gießen (Marktplatz 11)") == (
        imported.resolve_location_exact("Marktplatz 11")
    )
    assert imported.resolve_location_exact("Gießen (Marktplatz 11)") != (
        imported.resolve_location_exact("Gießen")
    )


def test_missing_supplemental_parent_is_created_before_its_child():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": ["Deutschland"],
            "Deutschland": [],
        }
    )
    calls = []
    imported = import_taxonomy(
        taxonomy,
        lambda label, parent_id=None, **kwargs: (
            calls.append((label, parent_id)) or len(calls)
        ),
    )

    genoa_id = imported.ensure_location_concept("Genua")
    italy_id = imported.resolve_location_exact("Italien")
    trieste_id = imported.ensure_location_concept("Triest")
    go_id = imported.resolve_location_exact("GO – geographischer Ort")

    assert genoa_id is not None and trieste_id is not None
    assert italy_id is not None
    assert calls[-3:] == [
        ("Italien", go_id),
        ("Genua", italy_id),
        ("Triest", italy_id),
    ]
    assert imported.nodes_by_key[("go", "supplemental", "genua")].parent_key == (
        "go",
        "supplemental",
        "italien",
    )


def test_disambiguated_sennfeld_gets_a_supplemental_concept_under_germany():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": ["Deutschland"],
            "Deutschland": ["Gießen"],
            "Gießen": ["Sennfeld"],
            "Sennfeld": [],
        }
    )
    # Give the mocked creator unique IDs so the parent relationship can be checked.
    next_id = iter(range(1, 20))
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: next(next_id))
    giessen_sennfeld_id = imported.resolve_location_exact("Sennfeld")
    adelsheim_sennfeld_id = imported.ensure_location_concept("Sennfeld (Adelsheim)")
    germany_id = imported.resolve_location_exact("Deutschland")

    assert adelsheim_sennfeld_id != giessen_sennfeld_id
    node = next(
        node
        for node in imported.nodes_by_key.values()
        if node.label == "Sennfeld (Adelsheim)"
    )
    germany_node = next(
        node for node in imported.nodes_by_key.values() if node.label == "Deutschland"
    )
    assert node.parent_key == germany_node.key
    assert germany_id is not None


def test_unknown_supplemental_location_requires_a_reviewed_parent_hint():
    taxonomy = Taxonomy(
        hierarchy={
            ROOT_KEY: ["GO – geographischer Ort"],
            "GO – geographischer Ort": [],
        }
    )
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: 1)

    try:
        imported.ensure_location_concept("Unknown Canonical Place")
    except ValueError as exc:
        assert "No canonical parent hint" in str(exc)
    else:
        raise AssertionError(
            "unreviewed locations must not be placed under the GO root"
        )


def test_reviewed_non_locations_remain_unmapped():
    from locations import taxonomy_match_excluded

    assert taxonomy_match_excluded("?")
    assert taxonomy_match_excluded(
        "Digitales Archiv vom Else-Lasker-Schüler-Gesellschaft"
    )
    assert not taxonomy_match_excluded("")
