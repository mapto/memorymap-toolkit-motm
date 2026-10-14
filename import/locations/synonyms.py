"""Load and query the reviewed location-to-GO synonym rules.

Source data names places in ways the GO taxonomy does not: spelling variants,
street addresses, and descriptive labels such as ``KZ Buchenwald``. Mapping
those labels to GO concepts needs human review, so the decisions live in one
file, ``data/location_taxonomy_synonyms.json``, and this module reads it. The
file has five sections. ``aliases`` maps a source label to its reviewed GO
label. ``canonical_parents`` names the GO parent of a supplemental location.
``excluded_contains`` lists substrings that mark a label as deliberately
unmapped. ``reviewed_unmapped`` lists labels that are not locations at all.
``query_overrides`` gives the geocoder query for one exact source label.

The file is read once per process and cached. The module makes no network or
database calls. Callers include ``taxonomy_import`` and ``rebuild_locations``
for GO matching and geocoding, ``names`` and ``entities`` for canonical names
and exclusions, and ``person_biography`` for aliases. ``validate_data`` parses
the same file on its own and reuses ``taxonomy_label_key``.
"""

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
    """Normalize a location label for taxonomy synonym matching.

    Hyphens and underscores become spaces, other punctuation becomes a space,
    case is folded, and runs of whitespace collapse to one space. Word order is
    kept, which separates this key from ``normalize_location``. The alias, parent,
    and exclusion keys are built with it, and so are the lookups against them.

    >>> taxonomy_label_key("Frankfurt_Main")
    'frankfurt main'
    """
    value = re.sub(r"[-_]+", " ", str(value or "").casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


@dataclass(frozen=True)
class LocationTaxonomySynonyms:
    """Represent the reviewed location-to-GO synonym rules, keyed for matching.

    ``location_taxonomy_synonyms()`` builds one instance from the JSON file.
    Callers use the module-level ``taxonomy_*`` wrappers instead of this class.
    Most keys are normalized with ``taxonomy_label_key`` when the table is
    built. Query overrides are the exception: they match exact source labels.
    The mappings are read-only; copy them before changing anything.
    """

    aliases: Mapping[str, str]
    canonical_parents: Mapping[str, str]
    excluded_terms: frozenset[str]
    reviewed_unmapped_keys: frozenset[str]
    reviewed_unmapped_labels: frozenset[str]
    query_overrides: Mapping[str, str]

    def alias_for(self, value) -> str:
        """Return the reviewed canonical GO label, or the value when unreviewed.

        The lookup normalizes ``value`` with ``taxonomy_label_key``, so case and
        punctuation differences do not matter. An unreviewed value comes back as
        passed, so callers can use the result in its place either way.
        """
        return self.aliases.get(taxonomy_label_key(value), value)

    def canonical_parent_for(self, value) -> str | None:
        """Return the reviewed GO parent label for a supplemental location, or None.

        The parent is the place under which a missing location concept is
        created. The lookup normalizes ``value`` with ``taxonomy_label_key``.
        """
        return self.canonical_parents.get(taxonomy_label_key(value))

    def query_override_for(self, value) -> str | None:
        """Return the reviewed geocoder query for an exact source label, or None.

        Matching is exact and case-sensitive, so the override applies only to the
        label as it is written in the table.
        """
        return self.query_overrides.get(value)

    def is_reviewed_unmapped(self, value) -> bool:
        """Return whether the reviewed table lists the label as not a location.

        A label matches when its case-folded, stripped text is listed, or when
        its ``taxonomy_label_key`` form is listed. Matching labels are dropped by
        the workbook rebuild and never receive a GO concept.
        """
        key = taxonomy_label_key(value)
        raw_value = str(value or "").strip().casefold()
        return bool(
            raw_value in self.reviewed_unmapped_labels
            or (key and key in self.reviewed_unmapped_keys)
        )

    def is_excluded(self, value) -> bool:
        """Return whether a reviewed location is intentionally left unmapped.

        True for every reviewed-unmapped label, and for any label whose key
        contains an ``excluded_contains`` term as a substring. Excluded labels get
        no GO concept, and ``sync_location_concepts`` reports them as unmapped.
        """
        key = taxonomy_label_key(value)
        return bool(
            self.is_reviewed_unmapped(value)
            or any(term in key for term in self.excluded_terms)
        )


@lru_cache(maxsize=1)
def location_taxonomy_synonyms() -> LocationTaxonomySynonyms:
    """Load the shared reviewed location-to-GO synonym table.

    Reads ``LOCATION_TAXONOMY_SYNONYMS_PATH`` on the first call and returns the
    cached result afterwards. Missing sections count as empty. A missing file
    raises ``OSError``, and malformed JSON raises ``json.JSONDecodeError``. Call
    ``location_taxonomy_synonyms.cache_clear()`` to reload after the file changes.
    """
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
    """Return the reviewed canonical GO label for a source synonym.

    Source spellings such as ``Frankfurt/M`` map to the GO label they stand for.
    Unreviewed labels come back unchanged. Used by ``names``, ``taxonomy_import``,
    ``rebuild_locations``, and ``person_biography``.
    """
    return location_taxonomy_synonyms().alias_for(value)


def taxonomy_match_excluded(value):
    """Return whether a source label is a reviewed exclusion from GO matching.

    Taxonomy resolution checks this first, so reviewed exclusions such as Koblenz
    never receive a GO concept. Used by ``taxonomy_import``, ``entities``, and
    ``rebuild_locations``.
    """
    return location_taxonomy_synonyms().is_excluded(value)


def taxonomy_reviewed_unmapped(value):
    """Return whether the reviewed table lists a source label as not a location.

    The workbook rebuild drops such labels, and ``canonical_location_name``
    returns None for them, so they never become location rows.
    """
    return location_taxonomy_synonyms().is_reviewed_unmapped(value)


def taxonomy_location_parent(value):
    """Return the reviewed GO parent label for a supplemental location, or None.

    ``taxonomy_import`` creates a missing location concept under this parent.
    ``rebuild_locations`` uses it to find the containing place when a location
    has no GO entry of its own.
    """
    return location_taxonomy_synonyms().canonical_parent_for(value)


def taxonomy_query_override(value):
    """Return the reviewed geocoder query for an exact source label, or None.

    ``rebuild_locations`` sends the override to the geocoder in place of the
    source label. Matching is exact, so case or spacing differences do not apply.
    """
    return location_taxonomy_synonyms().query_override_for(value)
