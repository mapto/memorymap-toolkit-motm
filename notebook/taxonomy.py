"""Parse the MQDA coding taxonomy from a Mermaid mindmap file.

Provides :func:`load_taxonomy` which reads ``docs/mqda_coding_taxonomy.mmd``
and returns a dict compatible with the former ``taxonomy.json`` structure::

    {
        "categories": {key: {"label": ..., "icon": ...}},
        "sub_categories": {key: {"label": ..., "parent": ...}},
        "concept_to_category": {label: category_key},
    }

>>> tax = load_taxonomy()
>>> "GO" in tax["categories"]
True
>>> tax["categories"]["GO"]["label"]
'GO – geographischer Ort'
"""

from __future__ import annotations

import re
from pathlib import Path


# Default icons for root categories.  Extend this dict to add icons for
# categories that don't have an abbreviation prefix.
ROOT_ICONS: dict[str, str] = {
    "GO": "fa-map-marker-alt",
    "TO": "fa-route",
    "OZ": "fa-clock",
    "SR": "fa-building",
    "LL": "fa-road",
    "AS": "fa-exclamation-triangle",
    "VM": "fa-bus",
    "F": "fa-people-arrows",
    "Zeitangaben": "fa-calendar",
    "Personae": "fa-user",
    "Kultureme": "fa-palette",
    "Figuren": "fa-theater-masks",
    "Religion": "fa-pray",
    "Zionismus": "fa-star-of-david",
    "Erinnerung": "fa-brain",
    "Identität": "fa-id-badge",
    "Jeckes": "fa-users",
    "'Ostjuden'": "fa-users",
    "code-switching": "fa-language",
    "Sprache(n)": "fa-language",
    "neue Heimat": "fa-house-flag",
    "alte Heimat": "fa-home",
    "Reise zurück": "fa-undo-alt",
    "Dokumentation": "fa-file-alt",
    "Generation": "fa-people-group",
    "Hilfe/Unterstützung": "fa-hands-helping",
    "Bemühungen um Auswanderung": "fa-passport",
    "Emotionen (Thematisierung)": "fa-heart",
    "Spuk": "fa-ghost",
    "Patriotismus (Vaterland)": "fa-flag",
}

_ABBREV_RE = re.compile(r"^([A-Z]{1,3})\s*[–\- ]\s*(?=[A-Za-zÄÖÜäöü])")


def _extract_key(label: str) -> str:
    """Extract a short key from a category label.

    Labels like 'GO – geographischer Ort' yield 'GO'.
    Labels without a prefix yield the full label.
    """
    m = _ABBREV_RE.match(label)
    return m.group(1) if m else label


def parse_mermaid_mindmap(path: str | Path) -> dict[str, list]:
    """Parse a Mermaid mindmap file into a tree.

    Returns a dict mapping each node label to its list of child labels,
    plus a special ``__roots__`` key listing the top-level nodes.
    """
    lines = Path(path).read_text().splitlines()
    children: dict[str, list[str]] = {"__roots__": []}
    stack: list[tuple[int, str]] = []  # (indent_level, label)

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "mindmap":
            continue
        if stripped.startswith("root("):
            continue  # skip the root node itself

        indent = len(line) - len(line.lstrip())
        # Remove backtick escaping
        label = stripped.strip("`").strip()
        if not label:
            continue

        # Pop stack until we find the parent at a lower indent
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if not stack:
            children["__roots__"].append(label)
        else:
            parent_label = stack[-1][1]
            children.setdefault(parent_label, []).append(label)

        children.setdefault(label, [])
        stack.append((indent, label))

    return children


def load_taxonomy(
    mmd_path: str | Path | None = None,
) -> dict:
    """Load taxonomy from a Mermaid mindmap file.

    Returns a dict with keys ``categories``, ``sub_categories``,
    and ``concept_to_category`` — compatible with the former
    ``taxonomy.json`` format.
    """
    if mmd_path is None:
        mmd_path = Path(__file__).resolve().parent.parent / "docs" / "mqda_coding_taxonomy.mmd"
    tree = parse_mermaid_mindmap(mmd_path)

    categories: dict[str, dict] = {}
    sub_categories: dict[str, dict] = {}
    concept_to_category: dict[str, str] = {}

    for root_label in tree["__roots__"]:
        key = _extract_key(root_label)
        icon = ROOT_ICONS.get(key, ROOT_ICONS.get(root_label, ""))
        categories[key] = {"label": root_label, "icon": icon}

        # Walk children → sub_categories and leaf concepts
        for child_label in tree.get(root_label, []):
            grandchildren = tree.get(child_label, [])
            if grandchildren:
                # This is a sub-category
                sub_key = f"{key}__{child_label}"
                sub_categories[sub_key] = {"label": child_label, "parent": key}
                for leaf in _walk_leaves(tree, child_label):
                    concept_to_category[leaf] = key
            else:
                # Direct child is a leaf concept
                concept_to_category[child_label] = key

    return {
        "categories": categories,
        "sub_categories": sub_categories,
        "concept_to_category": concept_to_category,
    }


def _walk_leaves(tree: dict[str, list], node: str) -> list[str]:
    """Recursively collect all leaf labels under *node*."""
    children = tree.get(node, [])
    if not children:
        return [node]
    leaves: list[str] = []
    for child in children:
        leaves.extend(_walk_leaves(tree, child))
    return leaves


if __name__ == "__main__":
    import doctest
    doctest.testmod()
    tax = load_taxonomy()
    print(f"Categories: {len(tax['categories'])}")
    for k, v in sorted(tax["categories"].items()):
        print(f"  {k}: {v['label']} (icon={v['icon']})")
    print(f"Sub-categories: {len(tax['sub_categories'])}")
    print(f"Concept-to-category mappings: {len(tax['concept_to_category'])}")
