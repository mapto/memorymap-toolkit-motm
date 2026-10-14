"""Value cleaning and parsing helpers for metadati workbooks.

Workbook cells arrive with mixed types: text with stray whitespace, years that
Excel stores as floats, dates written as text, empty cells, and dash
placeholders. The helpers here normalize these values before the sheet parsers
store them and before the API code sends them. Nothing in this module calls the
API.

``clean_value`` and ``clean_metadata_value`` return cleaned text or None.
``parse_name`` splits a person name into given and family names, and
``parse_source_label`` separates an interviewer from an archive ID. The
``_date_interval`` and ``_split_biographical_date_range`` helpers keep the
precision interval of partial dates, which ``timespans`` later uses to decide
whether two dates agree. ``clean_label`` builds the lookup key for relation
labels.
"""

from __future__ import annotations

import re
from utils import is_empty
from timespan import parse_timespan


# ---------------------------------------------------------------------------
# Utility helpers (metadati-specific)
# ---------------------------------------------------------------------------


def clean_label(label):
    """Return a lowercase lookup key for a label, without parentheses or dots.

    Used by ``relationships.get_or_create_relationship_type`` to match a relation
    label against ``RELATIONSHIP_MAP``. Whitespace runs are collapsed, so spacing
    differences in the workbook give the same key. The argument must be a string,
    since None raises AttributeError.

    >>> clean_label("Tante 1 (Schwester der Mutter)")
    'tante 1 schwester der mutter'
    """
    label = label.strip().lower()
    label = label.replace("(", "").replace(")", "")
    label = label.replace(".", "")
    label = " ".join(label.split())
    return label


def clean_value(value):
    """Return the stripped text of a cell, or None when it is empty.

    Accepts any cell type and converts it with ``str``. Blank text, ``nan``, and
    dash placeholders count as empty. Falsy inputs, including the number 0, return
    None before conversion.
    """
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
    """Return the (start, end) ISO dates that one metadata date stands for.

    A full date gives equal start and end. A partial date, such as a bare year,
    gives the whole period that ``timespan.parse_timespan`` reads from it. The
    pair is stored on the record, for example as ``birth_date_interval``, and
    ``timespans`` later uses it to decide whether two dates agree. Returns None
    when the text cannot be parsed.
    """
    parsed = parse_timespan(raw)
    if parsed.start is None:
        return None
    end = parsed.end or parsed.start
    return parsed.start.isoformat(), end.isoformat()


def _split_biographical_date_range(raw):
    """Split a family-table date cell into birth and death intervals.

    The cell may hold one date or a range, such as "1900–1950", "1900-50", or
    "1900 / 1950". The separators are tried in turn, and the first split that gives
    two parseable parts is used. A cell that cannot be split gives its whole value
    as the birth interval, with None as the death interval. An empty cell gives
    (None, None). Each part is converted by ``_date_interval``.
    """
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
    """Split a person name into ``(given_name, family_name)``.

    A name with a comma is read as "Family, Given". Otherwise the first word is the
    given name, and the remaining words form the family name. A single word becomes
    the given name, with ``"UNKNOWN"`` as the family name. Returns ``(None, None)``
    for an empty value. Used by ``interviews.create_interview`` for interviewers.
    """
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
    """Split a source label into ``(interviewer, archive_id)``.

    A label such as "Anne Betten, IS_E_00124" names the interviewer and then the
    archive ID. The archive ID is the first whole word shaped like uppercase
    letters, an underscore, one uppercase letter, an underscore, and digits. The
    text before it, stripped of spaces, commas, dashes, and plus signs, is the
    interviewer. Without an ID, the cleaned label is returned as the interviewer
    with None as the ID. An empty value gives (None, None). Called by
    ``sheets._parse_source_field`` for "Bezeichnung" rows.
    """
    source_label = clean_value(value)
    if not source_label:
        return None, None
    match = re.search(r"\b([A-Z]+_[A-Z]_\d+)\b", source_label)
    if not match:
        return source_label, None
    interviewer = source_label[: match.start()].strip(" ,\u2013-+") or None
    return interviewer, match.group(1)
