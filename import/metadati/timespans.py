"""Timespan lookup and lifespan updates for persons."""

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
    """Get or create a Timespan singleton. Returns id or None."""
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
    """Fill a person's lifespan without overwriting conflicting existing dates."""
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
