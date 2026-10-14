"""Place normalization, equivalence, and location lookups.

Chronotopi events, metadati workbooks, and Memory Map locations spell the same
place differently: ``Posen/Poznan``, ``Sennfeld (Adelsheim)``, ``Gießen``, and
``Giessen``. ``place_names_equivalent`` decides whether two spellings name the
same place. It compares normalized keys built from the cell text and from the
reviewed location aliases in ``locations``, using exact matching and no
similarity scores. Distinct places therefore stay distinct.

The other helpers clean a raw cell, merge place values across rows and sources,
and read the current name of a location for the validate and apply steps.
``metadati.places`` also calls ``place_names_equivalent`` to guard an existing
Person place link. Only ``_location_name`` reads the API, with GET requests that
are cached in a dict the caller owns.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping
from api_client import api_get
from locations import taxonomy_alias
from utils import clean_str


def _clean_place(value: Any) -> str | None:
    """Return the first line of a place cell, or None for a placeholder.

    Cells that hold ``?``, ``-``, ``n/a``, ``unknown``, or a bare number are read
    as no place. Without this, a placeholder would become a place name and clash
    with a real value. Only the first line of a multi-line cell is kept.
    """
    text = clean_str(value)
    place = text.splitlines()[0].strip() if text else ""
    if not place or place.casefold() in {"?", "-", "n/a", "unknown"}:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", place):
        return None
    return place


def _normalized_place(value: str) -> str:
    """Return a comparison key that ignores case, accents, punctuation, and word order.

    ``ß`` is replaced by ``ss`` first, and accents are removed. Words are sorted,
    so ``Oder Frankfurt`` and ``Frankfurt Oder`` get the same key, as do
    ``Poznań`` and ``Poznan``. A plain casefold comparison would miss both kinds
    of variant. The key is used only for equality tests, never for display.
    """
    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("ß", "ss"))
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(sorted(re.findall(r"[^\W_]+", unaccented, flags=re.UNICODE)))


def _place_match_keys(value: Any) -> set[str]:
    """Return every normalized key under which a place spelling can match.

    The cleaned place is always a candidate. When ``taxonomy_alias`` gives a
    different reviewed label, that label is a candidate too. So are the text
    without a parenthetical detail, and each part of a ``/`` alternative such as
    ``Posen/Poznan``. Each candidate is normalized with ``_normalized_place``. A
    visited set stops alias chains from looping. An empty or placeholder value
    gives an empty set, so ``place_names_equivalent`` returns False for it.
    """
    place = _clean_place(value)
    if not place:
        return set()
    candidates = [place]
    visited = set()
    keys = set()
    while candidates:
        candidate = candidates.pop()
        if candidate in visited:
            continue
        visited.add(candidate)
        alias = taxonomy_alias(candidate)
        if alias and alias != candidate:
            candidates.append(alias)
        without_parenthetical = re.sub(r"\s*\([^()]*\)", "", candidate).strip()
        if without_parenthetical != candidate:
            candidates.append(without_parenthetical)
        candidates.extend(
            part.strip() for part in re.split(r"\s*/\s*", candidate) if part.strip()
        )
        normalized = _normalized_place(candidate)
        if normalized:
            keys.add(normalized)
    return keys


def place_names_equivalent(left: Any, right: Any) -> bool:
    """Compare place spellings conservatively, allowing reviewed aliases/details.

    Returns True when the two values share at least one key from
    ``_place_match_keys``. A None or placeholder value never matches. Callers use
    this so that a second spelling of a known place does not raise a conflict.
    The function writes nothing; besides its arguments, it reads only the cached
    reviewed location alias table.
    """
    left_keys = _place_match_keys(left)
    return bool(left_keys and left_keys.intersection(_place_match_keys(right)))


def _merge_place(
    existing: str | None,
    incoming: str | None,
    *,
    description: str,
    conflicts: list[str],
) -> str | None:
    """Merge two place values for one field, keeping the existing spelling.

    When both values are present and not equivalent, a message that starts with
    ``description`` is appended to ``conflicts``, and the existing value is kept.
    Otherwise the incoming value fills an empty field, and an existing value is
    kept. The function never raises, so the caller reports the collected conflicts
    later. It is used wherever several rows or sources contribute to one place
    field.
    """
    if existing and incoming and not place_names_equivalent(existing, incoming):
        conflicts.append(f"{description}: {existing!r} conflicts with {incoming!r}")
        return existing
    return existing or incoming


def _location_name(location_id: Any, cache: dict[str, str | None]) -> str | None:
    """Return the current name of a Memory Map location, read through a cache.

    The first lookup of each ID makes one ``GET locations/{id}`` and stores the
    cleaned name in ``cache``, so a place shared by many Persons is read once per
    cache. The caller owns the dict. A response that is not a JSON object gives
    None, and the callers then leave the Person's place unchanged. HTTP errors
    are not caught here.
    """
    key = str(location_id)
    if key not in cache:
        location = api_get(f"locations/{location_id}")
        cache[key] = (
            _clean_place(location.get("current_name") or location.get("name"))
            if isinstance(location, Mapping)
            else None
        )
    return cache[key]
