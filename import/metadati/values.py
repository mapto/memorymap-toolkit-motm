"""Value cleaning and parsing helpers for metadati workbooks."""

from __future__ import annotations

import re
from utils import is_empty
from timespan import parse_timespan


# ---------------------------------------------------------------------------
# Utility helpers (metadati-specific)
# ---------------------------------------------------------------------------


def clean_label(label):
    label = label.strip().lower()
    label = label.replace("(", "").replace(")", "")
    label = label.replace(".", "")
    label = " ".join(label.split())
    return label


def clean_value(value):
    if not value:
        return None
    value = str(value).strip()
    if is_empty(value):
        return None
    return value


def clean_metadata_value(value):
    value = clean_value(value)
    return " ".join(value.split()) if value else None


def _date_interval(raw):
    """Preserve the precision interval represented by one metadata date."""
    parsed = parse_timespan(raw)
    if parsed.start is None:
        return None
    end = parsed.end or parsed.start
    return parsed.start.isoformat(), end.isoformat()


def _split_biographical_date_range(raw):
    """Return separate birth/death intervals from a metadata family date cell."""
    value = clean_value(raw)
    if not value:
        return None, None

    separators = [r"\s*[–—]\s*", r"\s+-\s+", r"-(?=[A-Za-zÄÖÜäöü])"]
    if re.fullmatch(r"\d{4}-\d{2,4}\??", value):
        separators.append(r"-")
    if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}\*?", value):
        separators.append(r"\s*/\s*")

    for separator in separators:
        match = re.search(separator, value)
        if not match:
            continue
        birth_interval = _date_interval(value[: match.start()])
        death_interval = _date_interval(value[match.end() :])
        if birth_interval and death_interval:
            return birth_interval, death_interval

    return _date_interval(value), None


def parse_coordinates(text):
    match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", text)
    if match:
        return {"lat": float(match.group(1)), "lon": float(match.group(2))}
    return None


def parse_name(full_name):
    if not full_name:
        return None, None
    full_name = full_name.strip()
    if "," in full_name:
        parts = full_name.split(",")
        family_name = parts[0].strip()
        given_name = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
        return given_name, family_name
    parts = full_name.split()
    if len(parts) > 1:
        return parts[0], " ".join(parts[1:])
    return full_name, "UNKNOWN"


def parse_source_label(value):
    """Extract interviewer text and corpus ID from a metadata source label."""
    source_label = clean_value(value)
    if not source_label:
        return None, None
    match = re.search(r"\b([A-Z]+_[A-Z]_\d+)\b", source_label)
    if not match:
        return source_label, None
    interviewer = source_label[: match.start()].strip(" ,\u2013-+") or None
    return interviewer, match.group(1)
