"""API client for Memory Map Toolkit Django REST API.

Provides session management, CRUD helpers, and domain-specific
get_or_create_* functions for concepts, locations, persons, timespans, and URLs.
"""

from __future__ import annotations

import os
import re
import time

import requests
from requests.exceptions import ConnectionError as ReqConnectionError

from utils import clean_str, is_empty


# ---------------------------------------------------------------------------
# Session & config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("MMT_API_URL", "http://localhost:8000/motm/api")
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
    if params is None:
        params = {}
    params.setdefault("limit", 10000)
    resp = _retry(SESSION.get, f"{BASE_URL}/{endpoint}/", params=params)
    resp.raise_for_status()
    data = resp.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data


def api_post(endpoint, payload):
    resp = _retry(SESSION.post, f"{BASE_URL}/{endpoint}/", json=payload)
    resp.raise_for_status()
    return resp.json()


def api_patch(endpoint, obj_id, payload):
    resp = _retry(SESSION.patch, f"{BASE_URL}/{endpoint}/{obj_id}/", json=payload)
    resp.raise_for_status()
    return resp.json()


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


def get_or_create_concept(label):
    """Get or create a concept.  If *label* contains ' > ' it is treated as a
    hierarchy, e.g. "Gegenstand > Grammophon" creates parent "Gegenstand" and
    child "Grammophon" with the parent relationship set."""
    label = label.strip()
    if not label or label in ("nan", "None"):
        return None

    # Handle hierarchical labels like "Parent > Child"
    if " > " in label:
        parts = [p.strip() for p in label.split(" > ", 1)]
        parent_id = get_or_create_concept(parts[0])
        child_label = parts[1]
        child_key = child_label.lower()
        if child_key in _concept_cache:
            return _concept_cache[child_key]
        existing = api_get("concepts", params={"search": child_label})
        match = next((c for c in existing if c["label"].lower() == child_key), None)
        if match:
            _concept_cache[child_key] = match["id"]
            if parent_id and match.get("parent") != parent_id:
                api_patch("concepts", match["id"], {"parent": parent_id})
            return match["id"]
        payload = {"label": child_label}
        if parent_id:
            payload["parent"] = parent_id
        created = api_post("concepts", payload)
        _concept_cache[child_key] = created["id"]
        return created["id"]

    key = label.lower()
    if key in _concept_cache:
        return _concept_cache[key]
    existing = api_get("concepts", params={"search": label})
    match = next((c for c in existing if c["label"].lower() == key), None)
    if match:
        _concept_cache[key] = match["id"]
        return match["id"]
    created = api_post("concepts", {"label": label})
    _concept_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------

_person_cache = {}


def get_person_id(protagonist_col, name_col):
    """Get or create a Person from the protagonist + name columns."""
    raw_name = clean_str(name_col)
    if not raw_name:
        raw_name = clean_str(protagonist_col)
    if not raw_name:
        return None
    key = raw_name.lower()
    if key in _person_cache:
        return _person_cache[key]
    parts = raw_name.split()
    given = parts[0] if parts else raw_name
    family = " ".join(parts[1:]) if len(parts) > 1 else raw_name
    existing = api_get("persons", params={"search": raw_name})
    for p in existing:
        if (
            p["given_name"].lower() == given.lower()
            and p["family_name"].lower() == family.lower()
        ):
            _person_cache[key] = p["id"]
            return p["id"]
    created = api_post("persons", {"given_name": given, "family_name": family})
    _person_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


def parse_interview_id_from_quelle(quelle):
    """Extract the interview ID from a quelle Markdown link.

    The quelle column format is:
        Interviewer Name – [IS_E_00124](https://dgd.ids-mannheim.de/...)
    Returns the link caption (e.g. 'IS_E_00124') or None.
    """
    if is_empty(quelle):
        return None
    m = re.search(r"\[([A-Z]+_[A-Z]_\d+)\]", quelle)
    return m.group(1) if m else None


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
