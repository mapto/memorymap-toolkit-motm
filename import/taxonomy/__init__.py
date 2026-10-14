"""Parse and validate the MQDA coding taxonomy from a Mermaid mindmap file.

This module owns the source-taxonomy side of the import boundary. It parses
the Mermaid tree, normalizes labels, validates the rule that a label occurs at
most once within a top-level category, and exposes an in-memory hierarchy.
It deliberately does not call the Memory Map API or create database records;
that keeps taxonomy interpretation deterministic and independently testable.
The persistence and source-label-to-ID work belongs to :mod:`taxonomy_import`.

Provides :func:`load_taxonomy` which reads ``docs/mqda_coding_taxonomy.mmd``
and returns a :class:`Taxonomy` dataclass with the following fields::

    categories: {key: {"label": ..., "icon": ...}}
    sub_categories: {key: {"label": ..., "parent": ...}}
    concept_to_category: {label: category_key}

The three special categories (Zeitangaben, Personae, GO) are pre-extracted
and removed from these structures, accessible via dedicated methods instead.

>>> tax = load_taxonomy()
>>> "Religion" in tax.categories
True
>>> "GO" in tax.categories  # Special categories are removed
False
"""

from taxonomy.keys import (
    ROOT_KEY,
    _ABBREV_RE,
    _extract_key,
    _label_key,
)

from taxonomy.model import (
    ROOT_ICONS,
    TaxonomyError,
    TaxonomyNode,
    TaxonomyOccurrence,
    _walk_leaves,
    _walk_all_nodes,
)

from taxonomy.mermaid import (
    parse_mermaid_occurrences,
    parse_mermaid_mindmap,
    parse_mmd_taxonomy,
)

from taxonomy.tree import (
    Taxonomy,
)

from taxonomy.loader import (
    load_taxonomy,
)

__all__ = [
    "ROOT_KEY",
    "_ABBREV_RE",
    "_extract_key",
    "_label_key",
    "ROOT_ICONS",
    "TaxonomyError",
    "TaxonomyNode",
    "TaxonomyOccurrence",
    "_walk_leaves",
    "_walk_all_nodes",
    "parse_mermaid_occurrences",
    "parse_mermaid_mindmap",
    "parse_mmd_taxonomy",
    "Taxonomy",
    "load_taxonomy",
]
