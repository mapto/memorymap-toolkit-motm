"""Date span parsing, intersection, and merging."""

from __future__ import annotations

from typing import Any, Mapping
from timespan import Timespan, parse_timespan
from utils import clean_str


def _parse_span(value: Any) -> Timespan | None:
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
    if span is None or span.start is None:
        return "unknown"
    end = span.end or span.start
    if span.start == end:
        return span.start.isoformat()
    return f"{span.start.isoformat()} through {end.isoformat()}"


def _event_date_span(row: Mapping[str, Any]) -> Timespan | None:
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
    stored = _parse_span(value)
    if stored is None:
        return None
    if metadata_span and metadata_span.start == stored.start:
        return metadata_span
    return Timespan(stored.start, stored.start, is_point=True)
