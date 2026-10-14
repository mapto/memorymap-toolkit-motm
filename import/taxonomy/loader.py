"""Loading the default MQDA taxonomy from the docs directory."""

from __future__ import annotations

from pathlib import Path
from taxonomy.mermaid import parse_mermaid_occurrences, parse_mermaid_mindmap
from taxonomy.tree import Taxonomy


def load_taxonomy(
    mmd_path: str | Path | None = None,
) -> Taxonomy:
    """Load taxonomy from a Mermaid mindmap file.

    Parses the mindmap and returns a :class:`Taxonomy` dataclass with
    ``hierarchy``, ``categories``, ``sub_categories``, and ``concept_to_category``
    fields automatically constructed from the parsed tree.
    """
    if mmd_path is None:
        mmd_path = (
            Path(__file__).resolve().parents[2] / "docs" / "mqda_coding_taxonomy.mmd"
        )
    tree = parse_mermaid_mindmap(mmd_path)
    occurrences = parse_mermaid_occurrences(mmd_path)
    return Taxonomy(hierarchy=tree, occurrences=occurrences)
