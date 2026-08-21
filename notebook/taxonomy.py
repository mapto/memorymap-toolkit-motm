"""Parse the MQDA coding taxonomy from a Mermaid mindmap file.

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

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from timespan import Timespan, parse_timespan


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
        _zeitangaben_data: pre-extracted leaf concepts under Zeitangaben.
        _personae_data: pre-extracted leaf concepts under Personae.
        _go_data: pre-extracted leaf geographic locations with hierarchical paths.
    """

    hierarchy: dict[str, list[str]]
    categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    sub_categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    concept_to_category: dict[str, str] = field(default_factory=dict, init=False)
    _zeitangaben_data: list[Timespan] = field(default_factory=list, init=False)
    _personae_data: list[str] = field(default_factory=list, init=False)
    _go_data: list[str] = field(default_factory=list, init=False)  # Will be built at method call time

    def __post_init__(self) -> None:
        """Build all taxonomy structures at construction time."""
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
                    # This is a sub-category (intermediate node)
                    sub_key = f"{key}__{child_label}"
                    sub_categories[sub_key] = {"label": child_label, "parent": key}
                    # Map the intermediate node itself (e.g., "1933" year node)
                    concept_to_category[child_label] = key
                    # Also map all leaves under it (e.g., "1. April 1933")
                    for leaf in _walk_leaves(self.hierarchy, child_label):
                        concept_to_category[leaf] = key
                else:
                    # Direct child is a leaf concept
                    concept_to_category[child_label] = key

        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "sub_categories", sub_categories)
        object.__setattr__(self, "concept_to_category", concept_to_category)

        # Extract zeitangaben, personae, and go at construction time
        # Use context-aware labels for dates/times (include year/parent in label)
        # Automatically detect and include all hierarchy levels present in the data
        zeitangaben_labels = self._build_concept_labels_with_context("Zeitangaben")
        # Parse each label to Timespan
        zeitangaben_list = [parse_timespan(label) for label in zeitangaben_labels]
        object.__setattr__(self, "_zeitangaben_data", zeitangaben_list)

        personae_list = self._build_concept_labels_with_context("Personae")
        object.__setattr__(self, "_personae_data", personae_list)

        # For GO, we need to build paths, but we'll do that lazily in the go() method
        # For now, just extract the labels
        go_labels = self._build_concept_labels_with_context("GO")
        object.__setattr__(self, "_go_data", go_labels)
        
        # Remove the three special categories from the general structures
        # since they're accessed via pre-extracted data instead
        special_categories = {"Zeitangaben", "Personae", "GO"}
        
        # Remove from categories
        categories = {k: v for k, v in self.categories.items() if k not in special_categories}
        
        # Remove from sub_categories (those with parent in special categories)
        sub_categories = {
            k: v for k, v in self.sub_categories.items()
            if v.get("parent") not in special_categories
        }
        
        # Remove from concept_to_category (those pointing to special categories)
        concept_to_category = {
            label: cat for label, cat in self.concept_to_category.items()
            if cat not in special_categories
        }
        
        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "sub_categories", sub_categories)
        object.__setattr__(self, "concept_to_category", concept_to_category)

    def zeitangaben(self) -> list[Timespan]:
        """Return all leaf concepts under the Zeitangaben category as Timespan objects.
        
        Returns pre-extracted data.

        >>> tax = load_taxonomy()
        >>> timespans = tax.zeitangaben()
        >>> len(timespans) > 0
        True
        >>> all(isinstance(ts, Timespan) for ts in timespans)
        True
        """
        return self._zeitangaben_data

    def personae(self) -> list[str]:
        """Return all leaf concepts under the Personae category.
        
        Returns pre-extracted data.

        >>> tax = load_taxonomy()
        >>> people = tax.personae()
        >>> 'Burgheim, Hedwig' in people
        True
        >>> len(people) > 0
        True
        """
        return self._personae_data

    def go(self) -> list[dict[str, str]]:
        """Return leaf geographic locations with compiled hierarchical paths.
        
        Returns pre-extracted data.

        >>> tax = load_taxonomy()
        >>> locations = tax.go()
        >>> len(locations) > 0
        True
        >>> all('label' in loc and 'address' in loc for loc in locations)
        True
        >>> any('Adlon' in loc['label'] for loc in locations)
        True
        """
        # Build result with paths
        result = []
        for concept_label in self._go_data:
            # Extract the main label (without context suffix for path building)
            main_label = concept_label.split(" ")[0] if " " in concept_label else concept_label
            path = self._build_path(main_label)
            result.append({"label": concept_label, "address": path})
        
        return result

    def _remove_subtree(self, category_key: str) -> None:
        """Remove a category and all its descendants from taxonomy structures.
        
        Updates categories, sub_categories, concept_to_category, and hierarchy.
        """
        # Find the category label from the key
        category_label = None
        for key, info in self.categories.items():
            if key == category_key:
                category_label = info["label"]
                break
        
        if not category_label:
            return  # Category not found
        
        # Collect all descendants of this category
        descendants = set()
        descendants.add(category_label)
        self._collect_descendants(category_label, descendants)
        
        # Remove from categories
        new_categories = {k: v for k, v in self.categories.items() if k != category_key}
        object.__setattr__(self, "categories", new_categories)
        
        # Remove from sub_categories and hierarchy
        new_sub_categories = {
            k: v for k, v in self.sub_categories.items()
            if v.get("parent") != category_key and k.split("__")[0] != category_key
        }
        object.__setattr__(self, "sub_categories", new_sub_categories)
        
        # Remove from concept_to_category
        new_concept_to_category = {
            label: cat for label, cat in self.concept_to_category.items()
            if cat != category_key
        }
        object.__setattr__(self, "concept_to_category", new_concept_to_category)
        
        # Remove from hierarchy
        new_hierarchy = {
            node: [child for child in children if child not in descendants]
            for node, children in self.hierarchy.items()
            if node not in descendants
        }
        object.__setattr__(self, "hierarchy", new_hierarchy)

    def _build_concept_labels_with_context(
        self, category_key: str
    ) -> list[str]:
        """Build concept labels for a category, automatically including all hierarchy levels.
        
        Automatically detects and includes all levels present in the data:
        - Direct children of category (e.g., years "1909", "1933")
        - Intermediate nodes (e.g., months "April 1933" under year "1933")
        - Leaf nodes (e.g., "1. April 1933" under month)
        
        Each leaf is labeled with its parent context when applicable.
        """
        labels = set()
        
        # Find the root category label
        category_label = None
        for key, info in self.categories.items():
            if key == category_key:
                category_label = info["label"]
                break
        
        if not category_label:
            return []
        
        # Helper to collect labels recursively, including all hierarchy levels
        def collect_labels(node: str, depth: int = 0, first_parent: str = "") -> None:
            children = self.hierarchy.get(node, [])
            
            # At depth 0 (direct children of category), this is our first parent context
            if depth == 0:
                labels.add(node)
                first_parent = node  # First-level children become the context for deeper nodes
            
            # Recurse into children
            for child in children:
                child_children = self.hierarchy.get(child, [])
                next_depth = depth + 1
                
                if not child_children:
                    # This is a leaf node - always combine with parent context if available
                    if first_parent:
                        labels.add(f"{child} {first_parent}")
                    else:
                        labels.add(child)
                else:
                    # This is an intermediate node with children
                    # If it's a direct child of a root node (depth==0), add it both ways
                    # Otherwise add with parent context
                    if depth == 0:
                        # Direct child like "April" under year "1933"
                        # Add just the child (e.g., "April")
                        labels.add(child)
                        # Also add with parent context (e.g., "April 1933")
                        labels.add(f"{child} {first_parent}")
                    else:
                        # Deeper intermediate nodes - add with parent context
                        labels.add(f"{child} {first_parent}")
                    # Recurse deeper, always passing first_parent
                    collect_labels(child, next_depth, first_parent)
        
        # Start collection from direct children of the category
        for child in self.hierarchy.get(category_label, []):
            collect_labels(child, 0, "")
        
        return sorted(labels)


    def _collect_descendants(self, node: str, descendants: set[str]) -> None:
        """Recursively collect all descendants of a node."""
        for child in self.hierarchy.get(node, []):
            if child not in descendants:
                descendants.add(child)
                self._collect_descendants(child, descendants)

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
    tax = load_taxonomy()
    print(f"Categories: {len(tax.categories)}")
    for k, v in sorted(tax.categories.items()):
        print(f"  {k}: {v['label']} (icon={v['icon']})")
    print(f"Sub-categories: {len(tax.sub_categories)}")
    print(f"Concept-to-category mappings: {tax.concept_to_category}")
