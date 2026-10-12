"""API client for Memory Map Toolkit Django REST API.

Provides session management, CRUD helpers, and domain-specific
get_or_create_* functions for concepts, locations, persons, timespans, and URLs.
"""

from __future__ import annotations

from datetime import date, datetime
import os
import re
import time

import requests
from requests.exceptions import ConnectionError as ReqConnectionError

from utils import clean_str, is_empty


# ---------------------------------------------------------------------------
# Session & config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("MMT_API_URL", "http://localhost:8000/en/motm/api")
LOGIN_URL = os.environ.get("MMT_LOGIN_URL", "http://localhost:8000/admin/login/")

SESSION = requests.Session()

_MAX_RETRIES = 5
_RETRY_DELAY = 3  # seconds


def _retry(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Retry *fn* on connection errors (e.g. Django auto-reload)."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (
            ReqConnectionError,
            requests.exceptions.ChunkedEncodingError,
            ConnectionResetError,
        ) as exc:
            if attempt == _MAX_RETRIES:
                raise
            print(
                f"  \u21bb connection lost (attempt {attempt}/{_MAX_RETRIES}), "
                f"retrying in {_RETRY_DELAY}s \u2026 ({exc.__class__.__name__})"
            )
            time.sleep(_RETRY_DELAY)
    raise RuntimeError("unreachable")  # keeps pyright happy


def login(username="admin", password="admin"):
    """Authenticate with the Django admin and configure CSRF headers."""
    SESSION.get(LOGIN_URL)
    SESSION.post(
        LOGIN_URL,
        data={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": SESSION.cookies["csrftoken"],
            "next": "/admin/",
        },
    )
    SESSION.headers["X-CSRFToken"] = SESSION.cookies.get("csrftoken") or ""
    SESSION.headers["Referer"] = LOGIN_URL
    ok = bool(SESSION.cookies.get("sessionid"))
    print("Authenticated" if ok else "Login failed")
    return ok


# ---------------------------------------------------------------------------
# Generic REST helpers
# ---------------------------------------------------------------------------


def api_get(endpoint, params=None):
    request_params = dict(params or {})
    request_params.setdefault("limit", 10000)
    url = f"{BASE_URL}/{endpoint}/"
    results = []

    while url:
        resp = _retry(SESSION.get, url, params=request_params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "results" not in data:
            return data
        results.extend(data["results"])
        url = data.get("next")
        # DRF's next URL already contains the original query parameters.
        request_params = None

    return results


def api_post(endpoint, payload, fail_on_error=True):
    resp = _retry(SESSION.post, f"{BASE_URL}/{endpoint}/", json=payload)
    if resp.status_code >= 400:
        error_msg = f"API Error {resp.status_code}: {resp.text}"
        print(f"  ⚠️ {error_msg}")
        if not fail_on_error:
            return None
    resp.raise_for_status()
    return resp.json()


def api_patch(endpoint, obj_id, payload):
    resp = _retry(SESSION.patch, f"{BASE_URL}/{endpoint}/{obj_id}/", json=payload)
    resp.raise_for_status()
    return resp.json()


def api_delete(endpoint, obj_id):
    resp = _retry(SESSION.delete, f"{BASE_URL}/{endpoint}/{obj_id}/")
    resp.raise_for_status()


def api_bulk_upsert(endpoint, items):
    """Create or update many objects in one request.

    Uses the ``bulk_upsert`` action on the viewset.  Each item is matched
    by the viewset's ``bulk_lookup_field``; matched records are updated,
    others are created.

    Returns the parsed response dict with ``created``, ``updated``, ``errors``,
    ``created_items``, and ``updated_items``.
    """
    resp = _retry(
        SESSION.post, f"{BASE_URL}/{endpoint}/bulk_upsert/", json={"items": items}
    )
    resp.raise_for_status()
    return resp.json()


def api_bulk_update(endpoint, items):
    """Update many objects by ID in one request.

    Each item in *items* must include an ``id`` field and any fields to update.

    Returns the parsed response dict with ``updated``, ``errors``,
    ``updated_items``.
    """
    resp = _retry(
        SESSION.patch, f"{BASE_URL}/{endpoint}/bulk_update/", json={"items": items}
    )
    resp.raise_for_status()
    return resp.json()


def api_bulk_create(endpoint, items):
    """Create many objects in one request (no matching/upsert).

    Returns the parsed response dict with ``created``, ``errors``, ``items``.
    """
    resp = _retry(
        SESSION.post, f"{BASE_URL}/{endpoint}/bulk_create/", json={"items": items}
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# String utilities  (canonical definitions live in utils.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

_concept_cache = {}


def get_or_create_concept(label, parent_id=None, icon=None, identity=None):
    """Get or create a concept.  If *label* contains ' > ' it is treated as a
    hierarchy, e.g. "Gegenstand > Grammophon" creates parent "Gegenstand" and
    child "Grammophon" with the parent relationship set.

    ``parent_id`` and ``identity`` let taxonomy imports distinguish equal
    labels in different top-level categories while reusing one ID for a
    repeated label within its category.
    """
    label = label.strip()
    if not label or label in ("nan", "None"):
        return None

    # Handle hierarchical labels like "Parent > Child"
    if " > " in label and parent_id is None:
        parts = [p.strip() for p in label.split(" > ", 1)]
        parent_id = get_or_create_concept(parts[0])
        return get_or_create_concept(
            parts[1], parent_id=parent_id, icon=icon, identity=identity
        )

    key = (identity or label.casefold(), parent_id)
    if key in _concept_cache:
        return _concept_cache[key]
    existing = api_get("concepts", params={"search": label})
    match = next(
        (
            c
            for c in existing
            if c["label"].casefold() == label.casefold()
            and c.get("parent") == parent_id
        ),
        None,
    )
    if match:
        updates = {}
        if icon and not match.get("icon"):
            updates["icon"] = icon
        if updates:
            api_patch("concepts", match["id"], updates)
        _concept_cache[key] = match["id"]
        return match["id"]
    payload = {"label": label}
    if parent_id is not None:
        payload["parent"] = parent_id
    if icon:
        payload["icon"] = icon
    created = api_post("concepts", payload)
    
    # Handle both single dict and list responses (from BulkMixin)
    if isinstance(created, list):
        if created:
            created = created[0]
        else:
            print(f"ERROR: Empty response when creating concept: {created}")
            return None
    
    concept_id = created.get("id")
    if not concept_id:
        print(f"ERROR: No 'id' in concept creation response: {created}")
        return None
    
    _concept_cache[key] = concept_id
    return concept_id


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------

_person_cache = {}


def _clean_person_name(value):
    value = clean_str(value)
    value = re.sub(r"\([^)]*\)", "", value)
    return " ".join(value.split()).strip(" ,\u2013-")


def _normalize_person_name(value):
    """Normalize a workbook name for comparison with split Person fields."""
    return _clean_person_name(value).casefold()


def _name_tokens(value):
    return _normalize_person_name(value).split()


def _is_subsequence(needles, haystack):
    iterator = iter(haystack)
    return all(any(token == candidate for candidate in iterator) for token in needles)


def _find_person_by_name(persons, raw_name):
    """Find one existing Person represented by a combined source name.

    Source sheets normally contain ``given family`` while the API returns
    separate fields. A first-name-plus-family match also handles database
    records with an additional middle name, such as ``Paul Avraham Alsberg``
    versus the source label ``Paul Alsberg``.
    """
    source_tokens = _name_tokens(raw_name)
    if len(source_tokens) < 2:
        return None

    candidates = []
    for person in persons:
        given_tokens = _name_tokens(person.get("given_name"))
        family_tokens = _name_tokens(person.get("family_name"))
        full_tokens = given_tokens + family_tokens
        if not full_tokens:
            continue
        exact_full = full_tokens == source_tokens
        exact_family = family_tokens == source_tokens[-1:]
        matching_edges = (
            full_tokens[0] == source_tokens[0]
            and full_tokens[-1] == source_tokens[-1]
        )
        if not matching_edges or not _is_subsequence(source_tokens, full_tokens):
            continue
        candidates.append(
            (
                (exact_full, exact_family, matching_edges, -len(full_tokens)),
                person,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    best_score, best_person = candidates[0]
    if len(candidates) > 1 and candidates[1][0] == best_score:
        return None
    return best_person


def get_person_id(protagonist_col, name_col):
    """Get or create a Person from a combined source name."""
    raw_name = clean_str(name_col)
    if not raw_name:
        raw_name = clean_str(protagonist_col)
    if not raw_name:
        return None
    key = _normalize_person_name(raw_name)
    if key in _person_cache:
        return _person_cache[key]
    display_name = _clean_person_name(raw_name)
    parts = display_name.split()
    given = " ".join(parts[:-1]) if len(parts) > 1 else display_name
    family = parts[-1] if len(parts) > 1 else display_name
    search_terms = [raw_name, *_normalize_person_name(raw_name).split()]
    existing_by_id = {}
    for search_term in dict.fromkeys(search_terms):
        for person in api_get("persons", params={"search": search_term}):
            existing_by_id[person["id"]] = person
    match = _find_person_by_name(list(existing_by_id.values()), raw_name)
    if match:
        _person_cache[key] = match["id"]
        return match["id"]
    created = api_post("persons", {"given_name": given, "family_name": family})
    _person_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


def normalize_interview_id(value):
    """Return the archive-ID format used by the Interview table.

    Source files sometimes omit zero-padding, for example ``IS_E_170``.
    Keeping normalization here means metadata and citation imports use the
    same lookup key.
    """
    archive_id = clean_str(value)
    if not archive_id:
        return None
    match = re.fullmatch(r"([A-Z]+_[A-Z])_(\d+)", archive_id)
    if not match:
        return archive_id
    return f"{match.group(1)}_{match.group(2).zfill(5)}"


def normalize_interview_date(value):
    """Convert supported spreadsheet date values to an ISO date string.

    A year-only source value is intentionally ignored because the database
    field is a full ``DateField`` and a fabricated month/day would mislead.
    """
    if is_empty(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw_value = clean_str(value)
    for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_value, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_interview_type(value):
    """Normalize the metadata workbook's interview-type label."""
    interview_type = clean_str(value)
    if not interview_type or interview_type.startswith("#"):
        return ""
    interview_type = re.sub(
        r"^Interview\s*", "", interview_type, flags=re.IGNORECASE
    )
    return interview_type.strip("()")


def build_interview_payload(
    archive_id,
    *,
    interviewee=None,
    interviewer=None,
    interview_type=None,
    interview_date=None,
    place=None,
    urls=None,
):
    """Build the canonical Interview payload shared by all importers."""
    archive_id = normalize_interview_id(archive_id)
    if not archive_id:
        return None

    payload = {"archive_id": archive_id}
    if interviewee:
        payload["interviewee"] = interviewee
    if interviewer:
        payload["interviewer"] = interviewer
    if interview_type is not None:
        payload["interview_type"] = normalize_interview_type(interview_type)
    if interview_date is not None:
        normalized_date = normalize_interview_date(interview_date)
        if normalized_date:
            payload["date"] = normalized_date
    if place is not None:
        payload["place"] = clean_str(place)
    if urls:
        payload["urls"] = list(urls)
    return payload


def upsert_interviews(payloads):
    """Upsert Interviews and return ``archive_id -> database ID`` plus errors.

    Payloads with the same archive ID are merged before one bulk API request,
    so metadata and Belege imports remain idempotent and share one write path.
    """
    merged_payloads = {}
    for payload in payloads:
        archive_id = normalize_interview_id(payload.get("archive_id"))
        if not archive_id:
            continue
        merged = merged_payloads.setdefault(archive_id, {"archive_id": archive_id})
        for field, value in payload.items():
            if field != "archive_id" and value not in (None, ""):
                if field == "urls":
                    merged[field] = list(dict.fromkeys(
                        [*merged.get(field, []), *value]
                    ))
                else:
                    merged[field] = value

    if not merged_payloads:
        return {}, []

    try:
        response = api_bulk_upsert("interviews", list(merged_payloads.values()))
    except Exception as exc:
        return {}, [f"interview bulk upsert: {exc}"]

    interview_ids = {}
    for item in [
        *response.get("created_items", []),
        *response.get("updated_items", []),
    ]:
        archive_id = normalize_interview_id(item.get("archive_id"))
        if archive_id and item.get("id") is not None:
            interview_ids[archive_id] = item["id"]

    errors = [
        f"interview {item.get('index', '?')}: {item.get('error', item)}"
        for item in response.get("errors", [])
    ]
    return interview_ids, errors


def parse_interview_id_from_quelle(quelle):
    """Extract the interview ID from a quelle Markdown link.

    The quelle column format is:
        Interviewer Name – [IS_E_00124](https://dgd.ids-mannheim.de/...)
    Returns the canonical archive ID (e.g. ``IS_E_00124``) or None. Some
    source rows omit zero-padding (``IS_E_170``), so the numeric suffix is
    normalized to the five-digit form used by the Interview table.
    """
    if is_empty(quelle):
        return None
    match = re.search(r"\[([A-Z]+_[A-Z]_\d+)\]", quelle)
    return normalize_interview_id(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Timespans
# ---------------------------------------------------------------------------

_timespan_cache = {}


def get_or_create_timespan(start, end, certainty=None):
    """Get or create a Timespan object."""
    key = (str(start), str(end), certainty)
    if key in _timespan_cache:
        return _timespan_cache[key]
    payload = {}
    if start:
        payload["start"] = str(start)
    if end:
        payload["end"] = str(end)
    if certainty:
        payload["certainty"] = certainty
    if not payload:
        return None
    created = api_post("timespans", payload)
    _timespan_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_url_cache = {}


def get_or_create_url(url_str):
    url_str = url_str.strip()
    if not url_str or url_str == "nan":
        return None
    if url_str in _url_cache:
        return _url_cache[url_str]
    existing = api_get("urls")
    for u in existing:
        if u["url"] == url_str:
            _url_cache[url_str] = u["id"]
            return u["id"]
    try:
        created = api_post("urls", {"url": url_str})
        _url_cache[url_str] = created["id"]
        return created["id"]
    except Exception as e:
        print(f"  URL creation failed for {url_str}: {e}")
        return None
