"""Parse German date expressions from the source workbooks into Timespans.

The Excel sheets and taxonomy labels record dates as free text, for example
``19. Januar 1913``, ``Januar 1934``, ``1930er Jahre``, ``194?``,
``ca. 1929–1935``, ``Ende 1942- Mai 1945``, or ``1932/Januar 1933``. A fixed
``strptime`` format cannot read these forms, and a plain ``date`` cannot hold
the end of a range or a certainty label. Each expression becomes a ``Timespan``
with a start, an end, a point flag, and a certainty label, so a year such as
``1942`` is kept as the whole year.

Parsing callers are ``events.py`` and ``validate_data.py`` (``parse_date``),
``metadati/sheets.py`` (``parse_date`` and ``parse_date_range``),
``metadati/values.py``, ``metadati/timespans.py``, ``person_biography/spans.py``,
``taxonomy/tree.py``, and ``chronotopi.ipynb`` (``parse_timespan``). The person
biography and taxonomy modules also use ``Timespan`` as a value type.

Run the embedded doctests with::

    python timespan.py
"""

from typing import Any
from datetime import date
import regex as re
import calendar

from dataclasses import dataclass


@dataclass(frozen=True)
class Timespan:
    """Represent an immutable time span with optional start and end dates.

    Source dates are often partial, such as a bare year, a decade, or a month.
    A Timespan keeps the known start and end together with a point flag and a
    certainty label, so a year is stored as the whole year rather than as one
    day. It is frozen so that callers cannot change the shared ``NAMED_PERIODS``
    instances that ``parse_timespan`` returns directly.

    Attributes:
        start: The start date (or the only known date).
        end: The end date. When ``is_point`` is True, coincides with start.
        is_point: True when the span represents a single moment in time
                  (start and end are known to coincide).
        certainty: Optional string indicating confidence level.
                   Values: ``"estimated"`` (set by ``parse_timespan``),
                   ``"certain"``, ``"probable"``, ``"uncertain"``, and
                   ``"disputed"`` (the vocabulary of the source
                   ``date_certainty`` column), or ``None`` (not set).

    >>> Timespan()
    Timespan(start=None, end=None, is_point=True, certainty=None)

    >>> Timespan(date(1922, 6, 19))  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1922, 6, 19), end=datetime.date(1922, 6, 19),
             is_point=True, certainty=None)

    >>> Timespan(date(1922, 6, 19), date(1945, 5, 8))  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1922, 6, 19), end=datetime.date(1945, 5, 8),
             is_point=False, certainty=None)

    >>> Timespan(date(1922, 6, 19),
    ...          certainty="probable")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1922, 6, 19), end=datetime.date(1922, 6, 19),
             is_point=True, certainty='probable')
    """

    start: date | None = None
    end: date | None = None
    is_point: bool = True
    certainty: str | None = None

    def __init__(
        self,
        start: date | None = None,
        end: date | None = None,
        *,
        is_point: bool | None = None,
        certainty: str | None = None,
    ):
        """Create a span, filling in the end date and point flag when omitted.

        ``end`` defaults to ``start``, so one date gives a point span. ``is_point``
        defaults to whether start and end coincide, so two different dates give a
        range without the caller saying so. The generated dataclass ``__init__``
        would leave ``end`` as None and mark every span as a point, which is why
        this explicit method is defined. ``is_point`` and ``certainty`` are
        keyword-only. The fields are set with ``object.__setattr__`` because the
        class is frozen.
        """
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end if end is not None else start)
        if is_point is None:
            object.__setattr__(self, "is_point", start == self.end)
        else:
            object.__setattr__(self, "is_point", is_point)
        object.__setattr__(self, "certainty", certainty)

    def as_tuple(self) -> tuple[date | None, date | None]:
        return (self.start, self.end)


MONTHS_DE = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
    "jan": 1,
    "feb": 2,
    "mär": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "okt": 10,
    "nov": 11,
    "dez": 12,
}

NAMED_PERIODS = {
    "1. weltkrieg": Timespan(
        date(1914, 7, 28), date(1918, 11, 11), is_point=False, certainty="estimated"
    ),
    "2. weltkrieg": Timespan(
        date(1939, 9, 1), date(1945, 9, 2), is_point=False, certainty="estimated"
    ),
}


def _last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _is_estimated_expr(s: str) -> bool:
    """Return True when one date expression lacks day-level precision.

    ``_certainty`` uses this to mark a span as ``"estimated"``. The imprecise
    forms are a fuzzy year (``194?``), a decade (``1930er Jahre``), a bare year
    (``1923``), and a word followed by a year (``Januar 1934``). Other trailing
    ``*`` and ``?`` markers are ignored. The check reads one expression at a
    time, so a range is checked one side at a time.

    >>> _is_estimated_expr("194?")
    True
    >>> _is_estimated_expr("1930er Jahre")
    True
    >>> _is_estimated_expr("1923")
    True
    >>> _is_estimated_expr("Januar 1934")
    True
    >>> _is_estimated_expr("19. Januar 1913")
    False
    >>> _is_estimated_expr("1941-08-25")
    False
    >>> _is_estimated_expr("28.1.1890")
    False
    """
    s = s.strip()
    if re.fullmatch(r"(\d{3})\?", s):
        return True
    s = s.rstrip("*").rstrip("?").strip()
    s = re.sub(r"\s+", " ", s)
    if re.fullmatch(r"(\d{4})er\s+jahre", s, re.IGNORECASE):
        return True
    if re.fullmatch(r"(\d{4})", s):
        return True
    if re.fullmatch(r"([a-zäöü]+\.?)\s+(\d{4})", s, re.IGNORECASE):
        return True
    return False


def _parse_partial_date_range(s: str) -> tuple[date, date] | None:
    """Parse one date expression into a ``(start, end)`` pair of dates.

    ``parse_timespan`` calls this for each side of a range and for a single
    expression. ``end`` is the last day of the precision the text gives: a full
    date maps to itself, a month to its last day, and a year or decade to
    31 December of its last year. A year or decade starts on 1 January of its
    first year. ISO dates ignore whatever follows the date, such as a time.
    Returns None when no pattern matches, and raises ``ValueError`` for an
    impossible calendar date.

    >>> _parse_partial_date_range("1941-08-25")
    (datetime.date(1941, 8, 25), datetime.date(1941, 8, 25))

    >>> _parse_partial_date_range("25/08/1941")
    (datetime.date(1941, 8, 25), datetime.date(1941, 8, 25))

    >>> _parse_partial_date_range("19. Januar 1913")
    (datetime.date(1913, 1, 19), datetime.date(1913, 1, 19))

    >>> _parse_partial_date_range("Januar 1934")
    (datetime.date(1934, 1, 1), datetime.date(1934, 1, 31))

    >>> _parse_partial_date_range("Sept. 1943")
    (datetime.date(1943, 9, 1), datetime.date(1943, 9, 30))

    >>> _parse_partial_date_range("1923")
    (datetime.date(1923, 1, 1), datetime.date(1923, 12, 31))

    >>> _parse_partial_date_range("194?")
    (datetime.date(1940, 1, 1), datetime.date(1949, 12, 31))

    >>> _parse_partial_date_range("1930er Jahre")
    (datetime.date(1930, 1, 1), datetime.date(1939, 12, 31))

    >>> _parse_partial_date_range("28.1.1890")
    (datetime.date(1890, 1, 28), datetime.date(1890, 1, 28))

    >>> _parse_partial_date_range("6.6.1896")
    (datetime.date(1896, 6, 6), datetime.date(1896, 6, 6))
    """
    s = s.strip()

    # Fuzzy year (194?) — before stripping ?
    m = re.fullmatch(r"(\d{3})\?", s)
    if m:
        year = int(m.group(1) + "0")
        return date(year, 1, 1), date(year + 9, 12, 31)

    s = s.rstrip("*").rstrip("?").strip()
    s = re.sub(r"\s+", " ", s)

    # ISO datetime: 1941-08-25 00:00:00
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, d

    # DD/MM/YYYY
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return d, d

    # DD.MM.YYYY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return d, d

    # DD. MonthName YYYY
    m = re.fullmatch(r"(\d{1,2})\.?\s+([a-zäöü]+\.?)\s+(\d{4})", s, re.IGNORECASE)
    if m:
        month = MONTHS_DE.get(m.group(2).lower().rstrip("."))
        if month:
            d = date(int(m.group(3)), month, int(m.group(1)))
            return d, d

    # MonthName YYYY → full month range
    m = re.fullmatch(r"([a-zäöü]+\.?)\s+(\d{4})", s, re.IGNORECASE)
    if m:
        month = MONTHS_DE.get(m.group(1).lower().rstrip("."))
        if month:
            year = int(m.group(2))
            return date(year, month, 1), _last_day(year, month)

    # Decade: 1930er Jahre
    m = re.fullmatch(r"(\d{4})er\s+jahre", s, re.IGNORECASE)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1), date(year + 9, 12, 31)

    # Plain year → full year range
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1), date(year, 12, 31)

    return None


def parse_timespan(raw: Any) -> Timespan:
    """Convert one raw spreadsheet value into a Timespan.

    The source workbooks hold dates as German free text. The rules for partial
    dates live in this one parser. Importers such as ``metadati/values.py`` and
    ``taxonomy/tree.py`` call it directly, and ``parse_date`` and
    ``parse_date_range`` call it too, so the importers share one reading. Blank
    input, ``-``, ``?``, and text that is not a date give an empty Timespan rather
    than None. An impossible calendar date such as ``31.02.1900`` raises
    ``ValueError``.

    Qualifiers such as ``ca.``, ``vor``, or ``nach`` and parenthesized notes are
    removed, and named periods such as ``1. Weltkrieg`` map to fixed dates. The
    rest is read as a range when it has an en dash, when it is a year range such
    as ``1928-1932``, ``1936-38``, or ``1938-194?``, when a hyphen is followed by
    a space or letter, or when it has a slash other than in DD/MM/YYYY. Text with
    no separator is a single expression that covers its full precision.
    Certainty is ``"estimated"`` when there is a qualifier, a named period, an
    ``Ende YYYY`` value, or any date less precise than a day. Otherwise it is
    None.

    >>> parse_timespan("19. Januar 1913")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1913, 1, 19), end=datetime.date(1913, 1, 19),
             is_point=True, certainty=None)

    >>> parse_timespan("ca. 1929–1935")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1929, 1, 1), end=datetime.date(1935, 12, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("Ende 1942- Mai 1945")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1942, 12, 31), end=datetime.date(1945, 5, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("1932/Januar 1933")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1932, 1, 1), end=datetime.date(1933, 1, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("1941-08-25")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1941, 8, 25), end=datetime.date(1941, 8, 25),
             is_point=True, certainty=None)

    >>> parse_timespan("25/08/1941*")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1941, 8, 25), end=datetime.date(1941, 8, 25),
             is_point=True, certainty=None)

    >>> parse_timespan("1930er Jahre")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1930, 1, 1), end=datetime.date(1939, 12, 31),
             is_point=True, certainty='estimated')

    >>> parse_timespan("1. Weltkrieg")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1914, 7, 28), end=datetime.date(1918, 11, 11),
             is_point=False, certainty='estimated')

    >>> parse_timespan("194?")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1940, 1, 1), end=datetime.date(1949, 12, 31),
             is_point=True, certainty='estimated')

    >>> parse_timespan("Während des Dienstes")
    Timespan(start=None, end=None, is_point=True, certainty=None)

    >>> parse_timespan("")
    Timespan(start=None, end=None, is_point=True, certainty=None)

    >>> parse_timespan("-")
    Timespan(start=None, end=None, is_point=True, certainty=None)

    >>> parse_timespan("1928-1932")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1928, 1, 1), end=datetime.date(1932, 12, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("1936-38")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1936, 1, 1), end=datetime.date(1938, 12, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("1938-194?")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1938, 1, 1), end=datetime.date(1949, 12, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("28.1.1890–1942")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1890, 1, 28), end=datetime.date(1942, 12, 31),
             is_point=False, certainty='estimated')

    >>> parse_timespan("22.5.1862–26.9.1942")  # doctest: +NORMALIZE_WHITESPACE
    Timespan(start=datetime.date(1862, 5, 22), end=datetime.date(1942, 9, 26),
             is_point=False, certainty=None)
    """
    if not raw:
        return Timespan()

    s = str(raw).strip().strip('"').strip()

    # Excel may expose integer years as floats, and some chronotopi sheets use
    # a year-first dotted date format alongside the usual German day-first one.
    if re.fullmatch(r"\d{4}\.0", s):
        s = s[:-2]
    year_first_dotted = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", s)
    if year_first_dotted:
        year, month, day = year_first_dotted.groups()
        s = f"{year}-{int(month):02d}-{int(day):02d}"

    # A few source labels omit the space after the day dot (for example,
    # ``03.Juli 1880``); normalize that spelling before parsing German dates.
    s = re.sub(r"(?<=\d)\.(?=[A-Za-zÄÖÜäöü])", ". ", s)

    if not s or s in ("-", "?"):
        return Timespan()

    # Named periods (already carry certainty)
    if s.lower() in NAMED_PERIODS:
        return NAMED_PERIODS[s.lower()]

    # Detect qualifier-based vagueness
    qualifiers = (
        r"^(ca\.\s*|ab\s+|vor\s+|nach\s+dem\s+|nach\s+|bis\s+|während\s+des\s+\w+\s*)"
    )
    estimated = bool(re.match(qualifiers, s, re.IGNORECASE))
    s_clean = re.sub(qualifiers, "", s, flags=re.IGNORECASE).strip()

    # Strip trailing annotations like "(ca. 2 Monate)"
    s_clean = re.sub(r"\(.*?\)", "", s_clean).strip()

    def _certainty(*parts: str) -> str | None:
        """Return ``"estimated"`` when a span is imprecise, otherwise None.

        ``try_range`` and the other branches of ``parse_timespan`` call this to
        set the certainty of each result. A qualifier from the enclosing call
        makes the span estimated. Otherwise any part (one side of a range, or the
        single expression) that ``_is_estimated_expr`` accepts, or that starts
        with ``Ende YYYY``, does. So a year-only or qualified date is marked
        ``"estimated"`` rather than left as None.
        """
        if estimated:
            return "estimated"
        for p in parts:
            if _is_estimated_expr(p) or re.match(r"(?i)ende\s+\d{4}", p.strip()):
                return "estimated"
        return None

    # "Ende YYYY" → last day of that year
    def parse_ende(part: str) -> tuple[date, date] | None:
        """Map an ``Ende YYYY`` expression to 31 December of that year.

        ``try_range`` and the single-value branch call this before
        ``_parse_partial_date_range``. ``Ende 1942`` means "at the end of 1942",
        so the point is 31 December 1942 rather than the whole year. Returns None
        for other text, so the caller can fall back to that function.
        """
        m = re.fullmatch(r"ende\s+(\d{4})", part.strip(), re.IGNORECASE)
        if m:
            d = date(int(m.group(1)), 12, 31)
            return d, d
        return None

    def try_range(left: str, right: str) -> Timespan:
        """Build a range from the expressions on either side of a separator.

        ``parse_timespan`` calls this for each en dash, hyphen, or slash
        separator. The start comes from the left expression and the end from the
        right one, each at its full precision. When only the left side parses,
        the span covers that side alone. When the left side does not parse, the
        result is empty even when the right side does, so that end date is
        discarded.
        """
        start_range = parse_ende(left) or _parse_partial_date_range(left)
        end_range = parse_ende(right) or _parse_partial_date_range(right)
        cert = _certainty(left, right)
        if start_range and end_range:
            return Timespan(
                start_range[0], end_range[1], is_point=False, certainty=cert
            )
        if start_range:
            return Timespan(
                start_range[0], start_range[1], is_point=False, certainty=cert
            )
        return Timespan()

    # En dash — always a range separator
    m = re.search(r"\s*–\s*", s_clean)
    if m:
        return try_range(s_clean[: m.start()], s_clean[m.end() :])

    # YYYY-YYYY (plain year range like 1928-1932)
    m = re.fullmatch(r"(\d{4})-(\d{4})", s_clean)
    if m:
        cert = _certainty(m.group(1), m.group(2))
        return Timespan(
            date(int(m.group(1)), 1, 1),
            date(int(m.group(2)), 12, 31),
            is_point=False,
            certainty=cert,
        )

    # YYYY-YY (short end year like 1936-38 → 1936-1938)
    m = re.fullmatch(r"(\d{4})-(\d{2})", s_clean)
    if m:
        century = m.group(1)[:2]
        end_year = int(century + m.group(2))
        return Timespan(
            date(int(m.group(1)), 1, 1),
            date(end_year, 12, 31),
            is_point=False,
            certainty=_certainty(m.group(1), m.group(2)),
        )

    # YYYY-YYY? (fuzzy short end year like 1938-194? → 1938 to 1940–1949)
    m = re.fullmatch(r"(\d{4})-(\d{3})\?", s_clean)
    if m:
        end_decade = int(m.group(2) + "0")
        return Timespan(
            date(int(m.group(1)), 1, 1),
            date(end_decade + 9, 12, 31),
            is_point=False,
            certainty="estimated",
        )

    # Hyphen — separator only if followed by space or letter (protects ISO dates)
    m = re.search(r"-\s+|-(?=[A-Za-zÄÖÜäöü])", s_clean)
    if m:
        return try_range(s_clean[: m.start()], s_clean[m.end() :])

    # Slash — range separator (1932/Januar 1933), but not in DD/MM/YYYY
    if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}\*?", s_clean):
        slash_sep = re.split(r"\s*/\s*", s_clean, maxsplit=1)
        if len(slash_sep) == 2:
            result = try_range(slash_sep[0], slash_sep[1])
            if result:
                return result

    # Single value — a single expression, not a range of two dates
    single = parse_ende(s_clean) or _parse_partial_date_range(s_clean)
    if single:
        cert = _certainty(s_clean)
        return Timespan(single[0], single[1], is_point=True, certainty=cert)

    return Timespan()


def parse_date(raw: Any) -> str | None:
    """Parse one date string and return the start of its span as ISO text.

    A single-date cell needs one ISO string, so this wraps ``parse_timespan`` and
    keeps only ``start``. ``events.py``, ``validate_data.py``, and
    ``metadati/sheets.py`` call it for such cells. For a range such as
    ``1928-1932`` the end is dropped; use ``parse_date_range`` to keep it. A bare
    year returns 1 January, and ``Ende 1942`` returns ``1942-12-31``. Returns None
    when there is no start, which includes blank and unparseable input.

    >>> parse_date("19.06.1922")
    '1922-06-19'

    >>> parse_date("28.1.1890")
    '1890-01-28'

    >>> parse_date("1942")
    '1942-01-01'

    >>> parse_date("")

    >>> parse_date("-")

    >>> parse_date("15. Juni 1921")
    '1921-06-15'
    """
    ts = parse_timespan(raw)
    if ts.start is None:
        return None
    return ts.start.isoformat()


def parse_date_range(raw: Any) -> tuple[str | None, str | None]:
    """Parse a date or date range string into ``(start_iso, end_iso)``.

    Used for the birth-date cell of the metadati sheets, which can hold a range.
    The start is the ISO start of the first expression. The end is the ISO end of
    the second, passed through ``_range_start_iso`` (see there for when an end is
    moved to the first day of its period). A single date returns ``(start, None)``
    because no second date is implied. Returns ``(None, None)`` when the input
    cannot be parsed.

    >>> parse_date_range("28.1.1890–1942")
    ('1890-01-28', '1942-01-01')

    >>> parse_date_range("22.5.1862–26.9.1942")
    ('1862-05-22', '1942-09-26')

    >>> parse_date_range("17.5.1896–1923")
    ('1896-05-17', '1923-01-01')

    >>> parse_date_range("19.6.1922")
    ('1922-06-19', None)

    >>> parse_date_range("1942")
    ('1942-01-01', None)

    >>> parse_date_range("")
    (None, None)

    >>> parse_date_range("-")
    (None, None)
    """
    ts = parse_timespan(raw)
    if ts.start is None and ts.end is None:
        return None, None

    start = ts.start.isoformat() if ts.start else None
    if ts.is_point:
        return start, None
    end = _range_start_iso(ts.end) if ts.end else None
    return start, end


def _range_start_iso(d: date) -> str:
    """Convert date to ISO, collapsing 31 December and month-ends on the 29th to 31st.

    ``parse_date_range`` calls this for the end of each range. When parse_timespan
    expands "1942" to (1942-01-01, 1942-12-31), the end represents precision, not a
    true second date. For the Django DateField we want the canonical first day, so
    such an end becomes the first day of its year or month. The rule looks only at
    the date, so an explicit end such as 30.9.1942 is also collapsed, to
    1942-09-01.

    >>> _range_start_iso(date(1942, 12, 31))
    '1942-01-01'

    >>> _range_start_iso(date(1942, 9, 26))
    '1942-09-26'

    >>> _range_start_iso(date(1934, 1, 31))
    '1934-01-01'

    >>> _range_start_iso(date(1922, 6, 19))
    '1922-06-19'
    """
    # If it's Dec 31, it was a year-only parse → use Jan 1
    if d.month == 12 and d.day == 31:
        return date(d.year, 1, 1).isoformat()
    # If it's the last day of a month, it was a month-only parse → use 1st
    if d.day == calendar.monthrange(d.year, d.month)[1] and d.day > 28:
        return date(d.year, d.month, 1).isoformat()
    return d.isoformat()


if __name__ == "__main__":
    import doctest

    doctest.testmod(verbose=True)
