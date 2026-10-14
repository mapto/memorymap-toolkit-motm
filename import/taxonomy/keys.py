"""Shared key helpers and the root sentinel for taxonomy trees."""

from __future__ import annotations

import re


# Key used in the tree returned by parse_mermaid_mindmap() to list top-level
# (root) node labels.
ROOT_KEY = "__roots__"


_ABBREV_RE = re.compile(r"^([A-Z]{1,3})\s*[–\- ]\s*(?=[A-Za-zÄÖÜäöü])")


def _extract_key(label: str) -> str:
    """Extract a short key from a category label.

    >>> _extract_key('GO – geographischer Ort')
    'GO'
    >>> _extract_key('Personae')
    'Personae'
    """
    m = _ABBREV_RE.match(label)
    return m.group(1) if m else label


def _label_key(label: str) -> str:
    """Normalize labels for import-time identity matching."""
    return " ".join(
        label.strip().casefold().replace("-", " ").replace("_", " ").split()
    )
