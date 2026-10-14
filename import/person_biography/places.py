"""Place normalization, equivalence, and location lookups."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping
from api_client import api_get
from locations import taxonomy_alias
from utils import clean_str


def _clean_place(value: Any) -> str | None:
    text = clean_str(value)
    place = text.splitlines()[0].strip() if text else ""
    if not place or place.casefold() in {"?", "-", "n/a", "unknown"}:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", place):
        return None
    return place


def _normalized_place(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("ß", "ss"))
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(sorted(re.findall(r"[^\W_]+", unaccented, flags=re.UNICODE)))


def _place_match_keys(value: Any) -> set[str]:
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
    """Compare place spellings conservatively, allowing reviewed aliases/details."""
    left_keys = _place_match_keys(left)
    return bool(left_keys and left_keys.intersection(_place_match_keys(right)))


def _merge_place(
    existing: str | None,
    incoming: str | None,
    *,
    description: str,
    conflicts: list[str],
) -> str | None:
    if existing and incoming and not place_names_equivalent(existing, incoming):
        conflicts.append(f"{description}: {existing!r} conflicts with {incoming!r}")
        return existing
    return existing or incoming


def _location_name(location_id: Any, cache: dict[str, str | None]) -> str | None:
    key = str(location_id)
    if key not in cache:
        location = api_get(f"locations/{location_id}")
        cache[key] = (
            _clean_place(location.get("current_name") or location.get("name"))
            if isinstance(location, Mapping)
            else None
        )
    return cache[key]
