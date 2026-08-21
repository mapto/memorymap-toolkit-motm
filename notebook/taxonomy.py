"""Parse the MQDA coding taxonomy from a Mermaid mindmap file.

Provides :func:`load_taxonomy` which reads ``docs/mqda_coding_taxonomy.mmd``
and returns a :class:`Taxonomy` dataclass with the following fields::

    categories: {key: {"label": ..., "icon": ...}}
    sub_categories: {key: {"label": ..., "parent": ...}}
    concept_to_category: {label: category_key}

>>> tax = load_taxonomy()
>>> "GO" in tax.categories
True
>>> tax.categories["GO"]["label"]
'GO – geographischer Ort'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# Key used in the tree returned by parse_mermaid_mindmap() to list top-level
# (root) node labels.
ROOT_KEY = "__roots__"


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
    "EO": "fa-landmark",
    "NR": "fa-tree",
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
    "Hilfe / Unterstützung": "fa-hands-helping",
    "Bemühungen um Auswanderung": "fa-passport",
    "Emotionen (Thematisierung)": "fa-heart",
    "Spuk": "fa-ghost",
    "Patriotismus (Vaterland)": "fa-flag",
    "Patriotismus (deutsch)": "fa-shield",
    "Erzählmodus": "fa-book",
    "'Ostjuden' / 'Jeckes' (Diskurs)": "fa-people-group",
    "Erinnerung (Diskurs)": "fa-comments",
    "Dinge / Objekte": "fa-cube",
    "Positionierung": "fa-compass",
}

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


def parse_mermaid_mindmap(path: str | Path) -> dict[str, list]:
    """Parse a Mermaid mindmap file into a tree.

    Returns a dict mapping each node label to its list of child labels,
    plus a special :data:`ROOT_KEY` key listing the top-level nodes.
    """
    lines = Path(path).read_text().splitlines()
    children: dict[str, list[str]] = {ROOT_KEY: []}
    stack: list[tuple[int, str]] = []  # (indent_level, label)

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "mindmap":
            continue
        if stripped.startswith("root("):
            continue  # skip the root node itself

        indent = len(line) - len(line.lstrip())
        # Extract label from bracket notation ["..."] or backtick escaping
        label = stripped
        m = re.search(r'\["(.+?)"\]', label)
        if m:
            label = m.group(1)
        else:
            label = label.strip("`").strip()
        if not label:
            continue

        # Pop stack until we find the parent at a lower indent
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if not stack:
            children[ROOT_KEY].append(label)
        else:
            parent_label = stack[-1][1]
            children.setdefault(parent_label, []).append(label)

        children.setdefault(label, [])
        stack.append((indent, label))

    return children


@dataclass(frozen=True)
class Taxonomy:
    """Parsed MQDA coding taxonomy.

    Attributes:
        hierarchy: {node_label: [child_labels, ...]} tree structure from mindmap.
        categories: root category key -> {"label": ..., "icon": ...}.
        sub_categories: sub-category key -> {"label": ..., "parent": root_key}.
        concept_to_category: leaf concept label -> root category key.
    """

    hierarchy: dict[str, list[str]]
    categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    sub_categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    concept_to_category: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        """Build categories, sub_categories, and concept_to_category from hierarchy."""
        categories: dict[str, dict] = {}
        sub_categories: dict[str, dict] = {}
        concept_to_category: dict[str, str] = {}

        for root_label in self.hierarchy.get(ROOT_KEY, []):
            key = _extract_key(root_label)
            icon = ROOT_ICONS.get(key, ROOT_ICONS.get(root_label, ""))
            if not icon:
                print(f"No icon for: {key} ({root_label})")
            categories[key] = {"label": root_label, "icon": icon}

            # Walk children → sub_categories and leaf concepts
            for child_label in self.hierarchy.get(root_label, []):
                grandchildren = self.hierarchy.get(child_label, [])
                if grandchildren:
                    # This is a sub-category
                    sub_key = f"{key}__{child_label}"
                    sub_categories[sub_key] = {"label": child_label, "parent": key}
                    for leaf in _walk_leaves(self.hierarchy, child_label):
                        concept_to_category[leaf] = key
                else:
                    # Direct child is a leaf concept
                    concept_to_category[child_label] = key

        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "sub_categories", sub_categories)
        object.__setattr__(self, "concept_to_category", concept_to_category)

    def zeitangaben(self) -> list[str]:
        """Return all concepts under the Zeitangaben category.

        >>> tax = load_taxonomy()
        >>> dates = tax.zeitangaben()
        >>> '1909' in dates
        True
        >>> '1945' in dates
        True
        """
        return sorted([label for label, cat in self.concept_to_category.items() if cat == "Zeitangaben"])

    def personae(self) -> list[str]:
        """Return all concepts under the Personae category.

        >>> tax = load_taxonomy()
        >>> people = tax.personae()
        >>> 'Burgheim, Hedwig' in people
        True
        >>> len(people) > 0
        True
        """
        return sorted([label for label, cat in self.concept_to_category.items() if cat == "Personae"])

    def go(self) -> list[dict[str, str]]:
        """Return geographic locations with compiled hierarchical paths.
        
        Builds address strings by concatenating the hierarchy from root to leaf.

        >>> tax = load_taxonomy()
        >>> locations = tax.go()
        >>> len(locations) > 0
        True
        >>> all('label' in loc and 'address' in loc for loc in locations)
        True
        >>> any(loc['label'] == 'Berlin' for loc in locations)
        True
        """
        go_concepts = [label for label, cat in self.concept_to_category.items() if cat == "GO"]
        result = []
        for concept in sorted(go_concepts):
            path = self._build_path(concept)
            result.append({"label": concept, "address": path})
        return result

    def _build_path(self, node: str, visited: set[str] | None = None) -> str:
        """Build hierarchical path for a node by walking the hierarchy tree."""
        if visited is None:
            visited = set()
        if node in visited:
            return node  # Cycle detection
        visited.add(node)

        # Find parent by checking which nodes contain this one as a child
        for parent, children in self.hierarchy.items():
            if node in children and parent != ROOT_KEY:
                parent_path = self._build_path(parent, visited)
                return f"{parent_path}/{node}" if parent_path else node

        return node


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
            Path(__file__).resolve().parent.parent / "docs" / "mqda_coding_taxonomy.mmd"
        )
    tree = parse_mermaid_mindmap(mmd_path)
    return Taxonomy(hierarchy=tree)


def _walk_leaves(tree: dict[str, list], node: str) -> list[str]:
    """Recursively collect all leaf labels under *node*."""
    children = tree.get(node, [])
    if not children:
        return [node]
    leaves: list[str] = []
    for child in children:
        leaves.extend(_walk_leaves(tree, child))
    return leaves


def _walk_all_nodes(
    tree: dict[str, list], node: str, root: str, out: dict[str, str]
) -> None:
    """Recursively map every descendant of *node* to *root*."""
    for child in tree.get(node, []):
        out[child] = root
        _walk_all_nodes(tree, child, root, out)


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


if __name__ == "__main__":
    import doctest

    doctest.testmod()
    tax = load_taxonomy()
    print(f"Categories: {len(tax.categories)}")
    for k, v in sorted(tax.categories.items()):
        print(f"  {k}: {v['label']} (icon={v['icon']})")
    print(f"Sub-categories: {len(tax.sub_categories)}")
    print(f"Concept-to-category mappings: {len(tax.concept_to_category)}")
