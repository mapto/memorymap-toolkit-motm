"""Parsers for the MQDA Mermaid mindmap source."""

from __future__ import annotations

import re
from pathlib import Path
from taxonomy.keys import ROOT_KEY
from taxonomy.model import TaxonomyOccurrence, _walk_all_nodes


def parse_mermaid_occurrences(path: str | Path) -> tuple[TaxonomyOccurrence, ...]:
    """Parse a Mermaid mindmap while preserving repeated-label occurrences."""
    lines = Path(path).read_text().splitlines()
    occurrences: list[TaxonomyOccurrence] = []
    stack: list[tuple[int, int]] = []  # (indent_level, occurrence_index)

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "mindmap":
            continue
        if stripped.startswith("root("):
            continue  # skip the root node itself

        indent = len(line) - len(line.lstrip())
        # Extract label from bracket notation ["..."] or backtick escaping.
        label = stripped
        m = re.search(r'\["(.+?)"\]', label)
        if m:
            label = m.group(1)
        else:
            label = label.strip("`").strip()
        if not label:
            continue

        # Pop stack until we find the parent at a lower indent.
        while stack and stack[-1][0] >= indent:
            stack.pop()

        parent_index = stack[-1][1] if stack else None
        if parent_index is None:
            top_level = label
            path = (label,)
        else:
            parent = occurrences[parent_index]
            top_level = parent.top_level
            path = parent.path + (label,)
        occurrences.append(
            TaxonomyOccurrence(
                label=label,
                parent_index=parent_index,
                top_level=top_level,
                path=path,
            )
        )
        stack.append((indent, len(occurrences) - 1))

    return tuple(occurrences)


def parse_mermaid_mindmap(path: str | Path) -> dict[str, list]:
    """Parse a Mermaid mindmap file into a label-keyed compatibility tree.

    The importer uses :func:`parse_mermaid_occurrences` so repeated labels in
    different top-level categories retain distinct paths. This older dict
    representation remains available for taxonomy helpers and compatibility.
    """
    occurrences = parse_mermaid_occurrences(path)
    children: dict[str, list[str]] = {ROOT_KEY: []}
    for occurrence in occurrences:
        if occurrence.parent_index is None:
            children[ROOT_KEY].append(occurrence.label)
        else:
            parent = occurrences[occurrence.parent_index]
            children.setdefault(parent.label, []).append(occurrence.label)
        children.setdefault(occurrence.label, [])

    return children


def parse_mmd_taxonomy(path: str | Path) -> dict[str, str]:
    """Parse a Mermaid mindmap and return {label: top_level_label}.

    Every node in the tree is mapped to its root-level ancestor's label.
    This is a convenience wrapper around :func:`parse_mermaid_mindmap`.
    """
    tree = parse_mermaid_mindmap(path)
    mapping: dict[str, str] = {}
    for root_label in tree[ROOT_KEY]:
        mapping[root_label] = root_label
        _walk_all_nodes(tree, root_label, root_label, mapping)
    return mapping
