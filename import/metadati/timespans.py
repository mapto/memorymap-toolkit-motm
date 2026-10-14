"""Timespan lookup and lifespan updates for persons.

Birth and death dates in the metadati workbooks are text, and often partial: a
bare year, or a year with a question mark. Writing them as they are would either
duplicate Timespan rows or overwrite a more precise date already stored on the
Person. This module therefore reuses an existing Timespan with the same start and
end when one exists. For a Person who already has a lifespan, it fills an empty
bound from the workbook and keeps a stored bound that the workbook date confirms,
but raises on a conflict.

``people.get_or_create_person`` calls ``_maybe_update_lifespan`` for every matched
Person. The module writes to the API only: it may POST a Timespan, PATCH the
Person's lifespan, and DELETE a Timespan that no Person references any more.
"""

from __future__ import annotations

from api_client import BASE_URL, SESSION, api_get, api_post
from timespan import parse_timespan


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_timespan_cache: dict = {}


# ---------------------------------------------------------------------------
# Timespan (metadati-specific: searches API before creating)
# ---------------------------------------------------------------------------


def get_or_create_timespan(start=None, end=None):
    """Return the ID of a Timespan with these exact start and end, creating it.

    The existing Timespans are listed through the API, and one whose start and end
    match is reused. Otherwise a new Timespan is POSTed. Results are cached per
    process, keyed by the pair. Returns None when both values are None. Unlike
    ``api_client.get_or_create_timespan``, which POSTs on every cache miss, this
    function does not create a duplicate of an existing exact match.
    """
    if start is None and end is None:
        return None
    key = (start, end)
    if key in _timespan_cache:
        return _timespan_cache[key]
    existing = api_get("timespans")
    for ts in existing:
        if ts.get("start") == start and ts.get("end") == end:
            _timespan_cache[key] = ts["id"]
            return ts["id"]
    created = api_post("timespans", {"start": start, "end": end})
    _timespan_cache[key] = created["id"]
    return created["id"]


# ---------------------------------------------------------------------------
# Person matching
# ---------------------------------------------------------------------------


def _data_date_interval(data, field_name, value):
    """Return the (start, end) precision interval of one incoming date.

    Prefers the ``<field_name>_date_interval`` pair that ``values`` stored on the
    record, so that a bare year keeps its full range. Falls back to parsing
    ``value`` when that pair is missing or does not parse. Returns None when the
    value cannot be parsed. Used by ``_maybe_update_lifespan`` to feed
    ``_compatible_date_or_existing``.
    """
    interval = data.get(f"{field_name}_date_interval")
    if isinstance(interval, (tuple, list)) and len(interval) == 2:
        start = parse_timespan(interval[0])
        end = parse_timespan(interval[1])
        if start.start and end.start:
            return start.start, end.end or end.start
    parsed = parse_timespan(value)
    if parsed.start is None:
        return None
    return parsed.start, parsed.end or parsed.start


def _compatible_date_or_existing(current, incoming, interval, field_name, person_id):
    """Return the date to keep for one lifespan bound, or raise on a conflict.

    ``current`` is the stored date and ``incoming`` is the workbook date for the
    bound named by ``field_name``. ``interval`` is the (start, end) precision
    interval of the incoming date, or None. A missing or identical value keeps the
    stored one, and a missing stored value takes the incoming one. When the stored
    date's interval overlaps the incoming interval, the stored value is kept as the
    more specific one. Any other difference raises ``ValueError`` that names the
    Person, so the stored data is not overwritten.
    """
    if not incoming:
        return current
    if not current:
        return incoming
    if current == incoming:
        return current

    existing = parse_timespan(current)
    existing_start = existing.start
    existing_end = existing.end or existing.start
    incoming_start, incoming_end = interval or (None, None)
    if (
        existing_start
        and existing_end
        and incoming_start
        and incoming_end
        and existing_start <= incoming_end
        and incoming_start <= existing_end
    ):
        # Keep an existing, more specific value when an imported partial date
        # merely confirms that it falls within the same precision interval.
        return current

    raise ValueError(
        f"Refusing to overwrite Person {person_id} {field_name} date "
        f"{current!r} with conflicting metadata value {incoming!r}"
    )


def _maybe_update_lifespan(person_id, data):
    """Fill or refine a Person's lifespan from birth and death dates, safely.

    Called by ``people.get_or_create_person`` for every matched Person. Returns
    without a request when neither date is given. A Person without a lifespan gets
    a Timespan for the incoming dates. A Person with one has each bound merged by
    ``_compatible_date_or_existing``, and nothing is written when the result is
    unchanged. When the lifespan changes, the Person is PATCHed to the new
    Timespan, and the old one is deleted if no other Person references it.
    """
    birth = data.get("birth_date")
    death = data.get("death_date")
    if not birth and not death:
        return
    person = SESSION.get(f"{BASE_URL}/persons/{person_id}/").json()
    existing_ts_id = person.get("lifespan")
    cur_start = None
    cur_end = None
    if existing_ts_id:
        ts = SESSION.get(f"{BASE_URL}/timespans/{existing_ts_id}/").json()
        cur_start = ts.get("start")
        cur_end = ts.get("end")
        new_start = _compatible_date_or_existing(
            cur_start,
            birth,
            _data_date_interval(data, "birth", birth),
            "birth",
            person_id,
        )
        new_end = _compatible_date_or_existing(
            cur_end,
            death,
            _data_date_interval(data, "death", death),
            "death",
            person_id,
        )
        if new_start == cur_start and new_end == cur_end:
            return  # no change
    else:
        new_start = birth
        new_end = death
    new_ts_id = get_or_create_timespan(start=new_start, end=new_end)
    if new_ts_id and new_ts_id != existing_ts_id:
        SESSION.patch(f"{BASE_URL}/persons/{person_id}/", json={"lifespan": new_ts_id})
        # Remove old timespan from cache and delete if orphaned
        if existing_ts_id:
            old_key = (cur_start, cur_end)
            _timespan_cache.pop(old_key, None)
            # Delete orphaned timespan (no other person references it after update)
            referencing = api_get("persons", params={"search": ""})
            still_used = any(p.get("lifespan") == existing_ts_id for p in referencing)
            if not still_used:
                SESSION.delete(f"{BASE_URL}/timespans/{existing_ts_id}/")
