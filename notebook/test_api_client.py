"""Unit tests for shared API-client behavior used by notebook imports."""

import api_client


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_api_get_follows_drf_pagination(monkeypatch):
    calls = []
    pages = iter(
        [
            {
                "results": [{"id": 1}],
                "next": "http://test/api/persons/?page=2",
            },
            {"results": [{"id": 2}], "next": None},
        ]
    )

    def fake_retry(function, url, params=None):
        calls.append((url, params))
        return FakeResponse(next(pages))

    monkeypatch.setattr(api_client, "_retry", fake_retry)

    assert api_client.api_get("persons", params={"search": "Stern"}) == [
        {"id": 1},
        {"id": 2},
    ]
    assert calls == [
        (
            "http://localhost:8000/en/motm/api/persons/",
            {"search": "Stern", "limit": 10000},
        ),
        ("http://test/api/persons/?page=2", None),
    ]


def test_build_interview_payload_normalizes_source_values():
    assert api_client.build_interview_payload(
        "IS_E_170",
        interviewee=7,
        interviewer=8,
        interview_type="Interview (oral)",
        interview_date="08.05.1991",
        place="Berlin",
    ) == {
        "archive_id": "IS_E_00170",
        "interviewee": 7,
        "interviewer": 8,
        "interview_type": "oral",
        "date": "1991-05-08",
        "place": "Berlin",
    }


def test_upsert_interviews_merges_duplicate_archive_ids(monkeypatch):
    calls = []

    def fake_bulk_upsert(endpoint, items):
        calls.append((endpoint, items))
        return {
            "created_items": [{"id": 17, **items[0]}],
            "updated_items": [],
            "errors": [],
        }

    monkeypatch.setattr(api_client, "api_bulk_upsert", fake_bulk_upsert)

    interview_ids, errors = api_client.upsert_interviews(
        [
            {"archive_id": "IS_E_170", "date": "1991-05-08"},
            {"archive_id": "IS_E_00170", "interviewee": 7},
        ]
    )

    assert errors == []
    assert interview_ids == {"IS_E_00170": 17}
    assert calls == [
        (
            "interviews",
            [{"archive_id": "IS_E_00170", "date": "1991-05-08", "interviewee": 7}],
        )
    ]


def test_get_person_id_matches_combined_name_to_split_fields(monkeypatch):
    person = {
        "id": 1,
        "given_name": "Irene Beatrice",
        "family_name": "Gaster",
    }
    posts = []

    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda endpoint, params=None: [person] if endpoint == "persons" else [],
    )
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: posts.append((endpoint, payload)),
    )
    api_client._person_cache.clear()

    assert api_client.get_person_id("Irene Beatrice", "Irene Beatrice Gaster") == 1
    assert posts == []


def test_get_person_id_matches_first_name_and_family_with_middle_name(monkeypatch):
    person = {
        "id": 1,
        "given_name": "Paul Avraham",
        "family_name": "Alsberg",
    }
    searches = []
    posts = []

    def fake_api_get(endpoint, params=None):
        if endpoint != "persons":
            return []
        searches.append(params["search"])
        return [person] if params["search"].casefold() == "alsberg" else []

    monkeypatch.setattr(api_client, "api_get", fake_api_get)
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: posts.append((endpoint, payload)),
    )
    api_client._person_cache.clear()

    assert api_client.get_person_id("Paul Alsberg", "Paul Alsberg") == 1
    assert searches == ["Paul Alsberg", "paul", "alsberg"]
    assert posts == []


def test_get_person_id_matches_simple_combined_name(monkeypatch):
    person = {"id": 3, "given_name": "Helena", "family_name": "Weinberg"}
    posts = []

    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda endpoint, params=None: [person] if endpoint == "persons" else [],
    )
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: posts.append((endpoint, payload)),
    )
    api_client._person_cache.clear()

    assert api_client.get_person_id("Helena Weinberg", "Helena Weinberg") == 3
    assert posts == []


def test_find_person_by_name_prefers_exact_family_field():
    persons = [
        {"id": 1, "given_name": "Paul Avraham", "family_name": "Alsberg"},
        {"id": 2, "given_name": "Paul", "family_name": "Avraham Alsberg"},
    ]

    assert api_client._find_person_by_name(persons, "Paul Alsberg")["id"] == 1


def test_find_person_by_name_ignores_parenthetical_role_annotation():
    persons = [{"id": 4, "given_name": "Frau Doktor", "family_name": "Nelken"}]

    assert api_client._find_person_by_name(
        persons, "Frau Doktor Nelken (Tante 2)"
    )["id"] == 4


def test_find_person_by_name_rejects_ambiguous_candidates():
    persons = [
        {"id": 5, "given_name": "Alex", "family_name": "Smith"},
        {"id": 6, "given_name": "Alex", "family_name": "Smith"},
    ]

    assert api_client._find_person_by_name(persons, "Alex Smith") is None


def test_get_person_id_preserves_display_case_when_creating_person(monkeypatch):
    posts = []

    monkeypatch.setattr(api_client, "api_get", lambda endpoint, params=None: [])
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: posts.append((endpoint, payload))
        or {"id": 7, **payload},
    )
    api_client._person_cache.clear()

    assert (
        api_client.get_person_id(
            "Frau Doktor Nelken (Tante 2)", "Frau Doktor Nelken (Tante 2)"
        )
        == 7
    )
    assert posts == [
        (
            "persons",
            {"given_name": "Frau Doktor", "family_name": "Nelken"},
        )
    ]


def test_get_person_id_returns_none_for_empty_name(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda endpoint, params=None: (_ for _ in ()).throw(
            AssertionError("empty names must not query the API")
        ),
    )
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: (_ for _ in ()).throw(
            AssertionError("empty names must not create a Person")
        ),
    )
    api_client._person_cache.clear()

    assert api_client.get_person_id("", None) is None


def test_get_person_id_reuses_cached_match(monkeypatch):
    person = {"id": 8, "given_name": "Helena", "family_name": "Weinberg"}
    searches = []

    def fake_api_get(endpoint, params=None):
        searches.append(params["search"])
        return [person]

    monkeypatch.setattr(api_client, "api_get", fake_api_get)
    api_client._person_cache.clear()

    assert api_client.get_person_id("Helena Weinberg", "Helena Weinberg") == 8
    assert api_client.get_person_id("Helena Weinberg", "Helena Weinberg") == 8
    assert searches == ["Helena Weinberg", "helena", "weinberg"]


def test_get_person_id_deduplicates_same_person_across_searches(monkeypatch):
    person = {"id": 9, "given_name": "Helena", "family_name": "Weinberg"}
    posts = []

    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda endpoint, params=None: [person] if endpoint == "persons" else [],
    )
    monkeypatch.setattr(
        api_client,
        "api_post",
        lambda endpoint, payload: posts.append((endpoint, payload)),
    )
    api_client._person_cache.clear()

    assert api_client.get_person_id("Helena Weinberg", "Helena Weinberg") == 9
    assert posts == []