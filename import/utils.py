"""Shared utility functions for the notebook import pipeline.

Source workbooks reach the import scripts through openpyxl and pandas. An empty
cell can therefore arrive as ``None``, as ``NaN``, as the text ``"nan"``, or as
a dash placeholder, and a whole number can arrive as a float such as ``12.0``.
The helpers here reduce those variants to one form before a value is compared,
stored, or sent to the API. They do no network or file I/O, which keeps them
easy to test offline. ``api_client`` names this module as the canonical home of
these string helpers, so importers should use these rather than local copies.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def clean_str(val):
    """Return cleaned string or empty string for nan/blank values.

    ``None``, ``NaN``, and the text ``"nan"`` or ``"None"`` all become ``""``, so
    callers can test one value for emptiness. A trailing ``.0`` is removed when
    the rest is all digits, so a whole number read as ``12.0`` becomes ``"12"``
    and matches its text form. Text such as ``"2.0"`` is shortened the same way.
    Other values return their ``str()`` form without surrounding whitespace.

    >>> clean_str(12.0)
    '12'
    >>> clean_str("nan")
    ''
    """
    s = str(val).strip()
    if s in ("", "nan", "None"):
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def is_empty(val) -> bool:
    """Check if a value is None, empty, nan, or a dash placeholder.

    ``None``, empty or whitespace-only text, ``"nan"``, ``"None"``, a hyphen, an
    en dash, and an em dash all count as empty. The dash forms are treated as
    placeholders, so importers skip them instead of sending them to the API. Zero
    and other real values return ``False``.

    >>> is_empty("-")
    True
    >>> is_empty(0)
    False
    """
    return val is None or str(val).strip() in (
        "",
        "nan",
        "None",
        "-",
        "\u2013",
        "\u2014",
    )


def extract_urls_from_text(text):
    """Extract URLs from a text field.

    Blank input and the text ``"nan"`` return an empty list. A match stops at
    whitespace and at characters such as angle brackets, quotes, braces, pipes,
    and square brackets. Other punctuation, such as a closing parenthesis or a
    full stop directly after a link, stays part of the match.
    """
    if not text or str(text).strip() in ("", "nan"):
        return []
    return re.findall(r"https?://[^\s<>\"{}|\\^`\[\]]+", str(text))


def extract_url_map(text: str) -> tuple[dict[str, str], str]:
    """Extract URLs from text into a {hostname: url} dict and remaining text.

    The URLs are found with the same pattern as ``extract_urls_from_text``. The
    dict is keyed by the hostname that ``urlparse`` reports, which is lowercased,
    so two URLs on one host collapse to the later one. The returned text is the
    input with every URL removed and the ends stripped. ``events.py`` reads the
    map values and ignores the text.

    Returns:
        A tuple of the hostname-to-URL dict and the remaining text.
    """
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(pattern, text)
    url_map = {urlparse(u).hostname: u for u in urls}
    remaining = re.sub(pattern, "", text).strip()
    return url_map, remaining.strip()


def extract_id_from_url(url):
    """Extract trailing ID segment from a URL (e.g. .../wiki/Q1794 -> Q1794).

    The text after the last ``/`` is returned, so a Wikidata link yields its
    ``Q`` identifier. Query strings are kept, and a trailing slash gives an empty
    string. Blank input and the text ``"nan"`` return ``None``. The callers are
    ``locations/db.py`` and ``rebuild_locations.py``.
    """
    if not url:
        return None
    url = str(url).strip()
    if not url or url == "nan":
        return None
    idx = url.rfind("/")
    return url[idx + 1 :] if idx >= 0 else url
