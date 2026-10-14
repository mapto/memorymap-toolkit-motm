"""Date span parsing, intersection, and merging.

Dates arrive as text in three forms: chronotopi event columns, metadati date
intervals, and dates already stored in Memory Map. This module turns each form
into a ``Timespan`` that keeps the precision of its source. A year from a metadata
workbook therefore stays a year instead of becoming an exact day. Spans are then
intersected to find the range that both sources agree on, or merged so that a
disagreement is recorded as a conflict. The module reads nothing and makes no API
calls.
"""

from __future__ import annotations

from typing import Any, Mapping
from timespan import Timespan, parse_timespan
from utils import clean_str


def _parse_span(value: Any) -> Timespan | None:
    """Parse one date text into a ``Timespan``, or return None.

    Empty text, text that ``parse_timespan`` rejects, an overflowing date, and a
    span without a start all return None. A span with a start but no end becomes a
    range that ends on its start. Returning None instead of raising lets each
    caller fall back to another field, such as the date label or the metadati
    value.
    """
    text = clean_str(value)
    if not text:
        return None
    try:
        parsed = parse_timespan(text)
    except (OverflowError, ValueError):
        return None
    if parsed.start is None:
        return None
    return Timespan(
        parsed.start,
        parsed.end or parsed.start,
        is_point=parsed.start == (parsed.end or parsed.start),
        certainty=parsed.certainty,
    )


def _span_from_interval(value: Any) -> Timespan | None:
    """Return a ``Timespan`` for a metadati date interval, or None.

    Metadati stores an interval as a two-item ``(start, end)`` pair of ISO date
    strings, which keeps a year-level range intact. A ``Timespan`` is returned
    unchanged when it has a start. Otherwise both items are parsed with
    ``_parse_span``. The result is None when either item fails to parse or the
    start is after the end, so ``_record_span`` falls back to the single date.
    """
    if isinstance(value, Timespan):
        return value if value.start else None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    start_span = _parse_span(value[0])
    end_span = _parse_span(value[1])
    if start_span is None or end_span is None:
        return None
    start = start_span.start
    end = end_span.end or end_span.start
    if start is None or end is None or start > end:
        return None
    return Timespan(start, end, is_point=start == end)


def _record_span(record: Mapping[str, Any], field_name: str) -> Timespan | None:
    interval = _span_from_interval(record.get(f"{field_name}_date_interval"))
    return interval or _parse_span(record.get(f"{field_name}_date"))


def _span_intersection(left: Timespan, right: Timespan) -> Timespan | None:
    """Return the overlap of two spans, or None when they do not overlap.

    A span without an end counts as one day at its start, and a span without a
    start never overlaps. Spans that touch on one day overlap, giving a one-day
    result. The overlap is the value kept when two spans for one field are merged.
    """
    if left.start is None or right.start is None:
        return None
    left_end = left.end or left.start
    right_end = right.end or right.start
    start = max(left.start, right.start)
    end = min(left_end, right_end)
    if start > end:
        return None
    return Timespan(start, end, is_point=start == end)


def _span_label(span: Timespan | None) -> str:
    """Return a short readable label for a span, for use in conflict messages.

    Returns ``"unknown"`` when there is no span or it has no start. A one-day span
    gives its ISO date, and a longer span gives ``start through end``. Labels are
    used only in messages.
    """
    if span is None or span.start is None:
        return "unknown"
    end = span.end or span.start
    if span.start == end:
        return span.start.isoformat()
    return f"{span.start.isoformat()} through {end.isoformat()}"


def _event_date_span(row: Mapping[str, Any]) -> Timespan | None:
    """Return the span for one chronotopi event row, preferring its date columns.

    An exact range comes from ``date_start`` and ``date_end`` when both parse. If a
    filled date column does not parse, ``date_label`` is used. Some sheets store a
    year-only event as January 1 in both columns, which looks like an exact day.
    When both columns give that one day and it is an end of a multi-day label
    range, the label range is returned so the year's precision is kept. Returns
    None when no usable date is present.
    """
    start_raw = clean_str(row.get("date_start", ""))
    end_raw = clean_str(row.get("date_end", ""))
    label_span = _parse_span(row.get("date_label", ""))
    start_span = _parse_span(start_raw) if start_raw else None
    end_span = _parse_span(end_raw) if end_raw else None

    if (start_raw and start_span is None) or (end_raw and end_span is None):
        return label_span
    first = start_span or end_span
    last = end_span or start_span
    if first is not None and last is not None:
        start = first.start
        end = last.end or last.start
        if start and end and start <= end:
            # Some sheets prefill year-only dates as Jan 1 in both event date
            # columns while retaining the year-only precision in date_label.
            # Recover that precision rather than treating the sentinel as exact.
            if (
                label_span
                and label_span.start
                and label_span.end
                and label_span.start < label_span.end
                and start == end
                and start in {label_span.start, label_span.end}
            ):
                return label_span
            return Timespan(start, end, is_point=start == end)
    return label_span


def _merge_span(
    existing: Timespan | None,
    incoming: Timespan | None,
    *,
    description: str,
    conflicts: list[str],
) -> Timespan | None:
    """Combine two spans for one field, recording a clash rather than raising.

    A missing side yields the other side. When both are present, their overlap is
    returned. If they do not overlap, a message made of ``description`` and both
    span labels is appended to ``conflicts``, and the existing span is returned
    unchanged. The caller decides when to report the collected conflicts.
    """
    if existing is None:
        return incoming
    if incoming is None:
        return existing
    intersection = _span_intersection(existing, incoming)
    if intersection is None:
        conflicts.append(
            f"{description}: {_span_label(existing)} conflicts with "
            f"{_span_label(incoming)}"
        )
        return existing
    return intersection


def _stored_date_span(
    value: Any,
    metadata_span: Timespan | None,
) -> Timespan | None:
    """Read a date already stored in Memory Map as a span, for comparison.

    The stored value is taken as a single day. If the metadata span starts on that
    same day, the metadata span is returned instead, so a year-level metadata range
    keeps its precision. Returns None when ``value`` is empty or cannot be parsed.
    """
    stored = _parse_span(value)
    if stored is None:
        return None
    if metadata_span and metadata_span.start == stored.start:
        return metadata_span
    return Timespan(stored.start, stored.start, is_point=True)
