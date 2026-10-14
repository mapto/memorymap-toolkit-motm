"""Name placeholders and key normalization for person matching."""

from __future__ import annotations

import re
import unicodedata

_NAME_PLACEHOLDERS = {"", "?", "unknown", "unbekannt", "n/a", "nan", "none"}


def person_taxonomy_key(value: str) -> str:
    """Normalize punctuation and spacing without guessing name-token order."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def _clean_name(value) -> str:
    return " ".join(str(value or "").strip().split()).strip(" ,\u2013-")


def is_placeholder_name(value) -> bool:
    """True for empty or unknown name parts such as "?" or "unbekannt"."""
    return _clean_name(value).casefold() in _NAME_PLACEHOLDERS
