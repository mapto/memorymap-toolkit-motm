"""Reviewed location-to-GO synonym rules."""

import json
import regex as re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


LOCATION_TAXONOMY_SYNONYMS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "location_taxonomy_synonyms.json"
)


def taxonomy_label_key(value):
    """Normalize a location label for taxonomy synonym matching."""
    value = re.sub(r"[-_]+", " ", str(value or "").casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


@dataclass(frozen=True)
class LocationTaxonomySynonyms:
    """Reviewed location-to-GO synonyms, with keys normalized for matching.

    Query overrides are the exception: they match exact source labels.
    The mappings are read-only; copy them before changing anything.
    """

    aliases: Mapping[str, str]
    canonical_parents: Mapping[str, str]
    excluded_terms: frozenset[str]
    reviewed_unmapped_keys: frozenset[str]
    reviewed_unmapped_labels: frozenset[str]
    query_overrides: Mapping[str, str]

    def alias_for(self, value) -> str:
        """Return the reviewed canonical GO label, or the value when unreviewed."""
        return self.aliases.get(taxonomy_label_key(value), value)

    def canonical_parent_for(self, value) -> str | None:
        """Return the reviewed GO parent hint for a supplemental location."""
        return self.canonical_parents.get(taxonomy_label_key(value))

    def query_override_for(self, value) -> str | None:
        """Return the reviewed geocoder query for an exact source label, if any."""
        return self.query_overrides.get(value)

    def is_reviewed_unmapped(self, value) -> bool:
        """Return whether the reviewed table lists the label as not a location."""
        key = taxonomy_label_key(value)
        raw_value = str(value or "").strip().casefold()
        return bool(
            raw_value in self.reviewed_unmapped_labels
            or (key and key in self.reviewed_unmapped_keys)
        )

    def is_excluded(self, value) -> bool:
        """Return whether a reviewed location is intentionally left unmapped."""
        key = taxonomy_label_key(value)
        return bool(
            self.is_reviewed_unmapped(value)
            or any(term in key for term in self.excluded_terms)
        )


@lru_cache(maxsize=1)
def location_taxonomy_synonyms() -> LocationTaxonomySynonyms:
    """Load the shared reviewed location-to-GO synonym table."""
    data = json.loads(LOCATION_TAXONOMY_SYNONYMS_PATH.read_text(encoding="utf-8"))
    reviewed_unmapped = data.get("reviewed_unmapped", [])
    return LocationTaxonomySynonyms(
        aliases=MappingProxyType(
            {
                taxonomy_label_key(source): target
                for source, target in data.get("aliases", {}).items()
            }
        ),
        canonical_parents=MappingProxyType(
            {
                taxonomy_label_key(source): target
                for source, target in data.get("canonical_parents", {}).items()
            }
        ),
        excluded_terms=frozenset(
            taxonomy_label_key(value) for value in data.get("excluded_contains", [])
        ),
        reviewed_unmapped_keys=frozenset(
            taxonomy_label_key(label) for label in reviewed_unmapped
        ),
        reviewed_unmapped_labels=frozenset(
            str(label).strip().casefold() for label in reviewed_unmapped
        ),
        query_overrides=MappingProxyType(dict(data.get("query_overrides", {}))),
    )


def taxonomy_alias(value):
    """Return the reviewed canonical GO label for a source synonym."""
    return location_taxonomy_synonyms().alias_for(value)


def taxonomy_match_excluded(value):
    """Return whether a reviewed location is intentionally left unmapped."""
    return location_taxonomy_synonyms().is_excluded(value)


def taxonomy_reviewed_unmapped(value):
    """Return whether the reviewed table lists a source label as not a location."""
    return location_taxonomy_synonyms().is_reviewed_unmapped(value)


def taxonomy_location_parent(value):
    """Return the reviewed GO parent hint for a supplemental location concept."""
    return location_taxonomy_synonyms().canonical_parent_for(value)


def taxonomy_query_override(value):
    """Return the reviewed geocoder query for an exact source label, if any."""
    return location_taxonomy_synonyms().query_override_for(value)
