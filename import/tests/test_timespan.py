"""Tests for parsing German date expressions into Timespan objects.

The importers call parse_timespan, parse_date, and parse_date_range on raw
workbook cells, so these tests pin the forms that the parser must read.
"""

import dataclasses
from datetime import date

import pytest

from timespan import (
    NAMED_PERIODS,
    Timespan,
    parse_date,
    parse_date_range,
    parse_timespan,
)


def _bounds(span):
    """Return the start, end, and certainty of a span for compact comparison."""
    return span.start, span.end, span.certainty


class TestParseTimespanExactDates:
    """Exact days parse to a point span with no certainty."""

    @pytest.mark.parametrize(
        ("raw", "day"),
        [
            ("19. Januar 1913", date(1913, 1, 19)),
            ("1941-08-25", date(1941, 8, 25)),
            ("25/08/1941*", date(1941, 8, 25)),
            ("03.Juli 1880", date(1880, 7, 3)),
            ("1924.10.30", date(1924, 10, 30)),
        ],
    )
    def test_full_date_is_a_point_without_certainty(self, raw, day):
        """A full date becomes a point on that day with certainty None."""
        span = parse_timespan(raw)
        assert span == Timespan(day, day, is_point=True, certainty=None)


class TestParseTimespanPartialDates:
    """Months, years, decades, and fuzzy years cover their whole period."""

    @pytest.mark.parametrize(
        ("raw", "start", "end"),
        [
            ("Januar 1934", date(1934, 1, 1), date(1934, 1, 31)),
            ("1923", date(1923, 1, 1), date(1923, 12, 31)),
            ("1974.0", date(1974, 1, 1), date(1974, 12, 31)),
            ("1930er Jahre", date(1930, 1, 1), date(1939, 12, 31)),
            ("194?", date(1940, 1, 1), date(1949, 12, 31)),
        ],
    )
    def test_partial_date_covers_its_period_as_estimated(self, raw, start, end):
        """A partial date spans its full period and is marked estimated."""
        assert _bounds(parse_timespan(raw)) == (start, end, "estimated")


class TestParseTimespanRanges:
    """A range keeps the start of its first side and the end of its last side."""

    @pytest.mark.parametrize(
        ("raw", "start", "end", "certainty"),
        [
            ("28.1.1890–1942", date(1890, 1, 28), date(1942, 12, 31), "estimated"),
            ("22.5.1862–26.9.1942", date(1862, 5, 22), date(1942, 9, 26), None),
            ("1928-1932", date(1928, 1, 1), date(1932, 12, 31), "estimated"),
            ("1936-38", date(1936, 1, 1), date(1938, 12, 31), "estimated"),
            ("1938-194?", date(1938, 1, 1), date(1949, 12, 31), "estimated"),
            ("ca. 1929–1935", date(1929, 1, 1), date(1935, 12, 31), "estimated"),
            ("1932/Januar 1933", date(1932, 1, 1), date(1933, 1, 31), "estimated"),
            (
                "Ende 1942- Mai 1945",
                date(1942, 12, 31),
                date(1945, 5, 31),
                "estimated",
            ),
        ],
    )
    def test_range_spans_both_sides(self, raw, start, end, certainty):
        """A range runs from the first side's start to the last side's end."""
        span = parse_timespan(raw)
        assert _bounds(span) == (start, end, certainty)
        assert span.is_point is False


class TestNamedPeriods:
    """Named periods return shared constants that callers cannot change."""

    def test_named_period_returns_the_shared_constant(self):
        """A named period returns the NAMED_PERIODS entry with its fixed dates."""
        span = parse_timespan("2. Weltkrieg")
        assert span is NAMED_PERIODS["2. weltkrieg"]
        assert _bounds(span) == (date(1939, 9, 1), date(1945, 9, 2), "estimated")

    def test_named_period_cannot_be_mutated(self):
        """Assigning to a returned period raises, because Timespan is frozen."""
        span = parse_timespan("1. Weltkrieg")
        with pytest.raises(dataclasses.FrozenInstanceError):
            # setattr hides this deliberate write from the type checker, which
            # rejects direct assignment to a frozen dataclass field.
            setattr(span, "start", date(2000, 1, 1))


class TestBlankAndInvalidInput:
    """Blank input gives an empty span, and an impossible date raises."""

    @pytest.mark.parametrize("raw", [None, "", "  ", "-", "?", "Während des Dienstes"])
    def test_blank_or_non_date_gives_empty_timespan(self, raw):
        """Each of these inputs returns a Timespan with no start or end."""
        assert parse_timespan(raw) == Timespan()

    def test_impossible_calendar_date_raises_value_error(self):
        """An impossible calendar date such as 31.02.1900 raises ValueError."""
        with pytest.raises(ValueError):
            parse_timespan("31.02.1900")


class TestTimespanConstructor:
    """The constructor fills in end and is_point when the caller omits them."""

    def test_single_date_becomes_a_point(self):
        """One date sets end to the same day and marks the span as a point."""
        span = Timespan(date(1922, 6, 19))
        assert span.end == date(1922, 6, 19)
        assert span.is_point is True

    def test_two_different_dates_become_a_range(self):
        """Two different dates give a range without an explicit is_point."""
        span = Timespan(date(1922, 6, 19), date(1945, 5, 8))
        assert span.is_point is False

    def test_explicit_is_point_overrides_the_default(self):
        """A caller-supplied is_point is kept even when start and end coincide."""
        span = Timespan(date(1922, 6, 19), date(1922, 6, 19), is_point=False)
        assert span.is_point is False


class TestParseDate:
    """parse_date returns the ISO start for single-date cells."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("19.06.1922", "1922-06-19"),
            ("28.1.1890", "1890-01-28"),
            ("15. Juni 1921", "1921-06-15"),
            ("1942", "1942-01-01"),
            ("Ende 1942", "1942-12-31"),
            ("28.1.1890–1942", "1890-01-28"),
        ],
    )
    def test_returns_iso_start(self, raw, expected):
        """Each form returns the ISO start of its span; a range keeps only its start."""
        assert parse_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "-", "Während des Dienstes"])
    def test_returns_none_without_a_start(self, raw):
        """Blank, placeholder, and non-date text return None."""
        assert parse_date(raw) is None


class TestParseDateRange:
    """parse_date_range returns ISO start and end for the metadati birth-date cell."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("28.1.1890–1942", ("1890-01-28", "1942-01-01")),
            ("22.5.1862–26.9.1942", ("1862-05-22", "1942-09-26")),
            ("17.5.1896–1923", ("1896-05-17", "1923-01-01")),
        ],
    )
    def test_range_returns_start_and_end(self, raw, expected):
        """A range returns its start, and a year-only end falls on 1 January."""
        assert parse_date_range(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("19.6.1922", ("1922-06-19", None)), ("1942", ("1942-01-01", None))],
    )
    def test_single_date_has_no_end(self, raw, expected):
        """A single date returns its start and None, since no end is implied."""
        assert parse_date_range(raw) == expected

    @pytest.mark.parametrize("raw", ["", "-"])
    def test_blank_returns_none_pair(self, raw):
        """Blank or placeholder input returns (None, None)."""
        assert parse_date_range(raw) == (None, None)
