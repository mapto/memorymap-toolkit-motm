"""Shared utility functions for the notebook import pipeline."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def clean_str(val):
    """Return cleaned string or empty string for nan/blank values."""
    s = str(val).strip()
    if s in ("", "nan", "None"):
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def is_empty(val) -> bool:
    """Check if a value is None, empty, nan, or a dash placeholder."""
    return val is None or str(val).strip() in (
        "",
        "nan",
        "None",
        "-",
        "\u2013",
        "\u2014",
    )


def extract_urls_from_text(text):
    """Extract URLs from a text field."""
    if not text or str(text).strip() in ("", "nan"):
        return []
    return re.findall(r"https?://[^\s<>\"{}|\\^`\[\]]+", str(text))


def extract_url_map(text: str) -> tuple[dict[str, str], str]:
    """Extract URLs from text into a {hostname: url} dict and remaining text."""
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(pattern, text)
    url_map = {urlparse(u).hostname: u for u in urls}
    remaining = re.sub(pattern, "", text).strip()
    return url_map, remaining.strip()


def extract_id_from_url(url):
    """Extract trailing ID segment from a URL (e.g. .../wiki/Q1794 -> Q1794)."""
    if not url:
        return None
    url = str(url).strip()
    if not url or url == "nan":
        return None
    idx = url.rfind("/")
    return url[idx + 1 :] if idx >= 0 else url
