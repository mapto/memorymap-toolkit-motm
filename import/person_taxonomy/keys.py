"""Name placeholders and key normalization for person matching.

Names arrive from spreadsheets with stray punctuation, mixed case, non-breaking
spaces, and placeholder values such as ``?`` or ``unbekannt``. Alias and leaf
lookups in this package compare names through ``person_taxonomy_key``, so
spellings that differ only in those details find the same alias and the same
Personae leaf. The key keeps token order on purpose: ``Stern, Josef`` and
``Josef Stern`` normalize differently, and choosing between them is the job of
the reviewed synonym table, not of normalization.

``is_placeholder_name`` lets callers skip unknown name parts, such as an
unnamed relative, instead of creating a leaf or alias for the placeholder.
"""

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
