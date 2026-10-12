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
    assert imported.resolve_concept("alte_heimat") == imported.resolve_concept("alte Heimat")
    assert len(shared_ids) == 2
    assert shared_ids[0] != shared_ids[1]


def test_import_taxonomy_returns_none_for_unknown_source_labels():
    taxonomy = Taxonomy(hierarchy={ROOT_KEY: ["Root"], "Root": []})
    imported = import_taxonomy(taxonomy, lambda label, **kwargs: 1)

    assert imported.resolve_concept("not in taxonomy") is None


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

    assert imported.resolve_location("Gießen Marktplatz 15") == imported.resolve_location("Gießen")
    assert imported.resolve_location("KZ Buchenwald (Buchenwald)") == imported.resolve_location("Buchenwald")
    yad_vashem_id = imported.ensure_location_concept("Yad Vashem")
    assert yad_vashem_id is not None
    assert imported.resolve_location_exact("Yad Vashem") == yad_vashem_id
    assert imported.ids_by_key[imported.nodes_by_key[('go', 'supplemental', 'yad vashem')].key] == yad_vashem_id
    assert imported.resolve_location("Koblenz") is None
    assert imported.resolve_location(
        "Gießen Marktplatz 15",
        allow_aliases=False,
        allow_embedded=False,
    ) is None
