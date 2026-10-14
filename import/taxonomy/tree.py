"""The Taxonomy class: validation, queries, and export helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from timespan import Timespan, parse_timespan
from taxonomy.keys import ROOT_KEY, _extract_key, _label_key
from taxonomy.model import (
    ROOT_ICONS,
    TaxonomyError,
    TaxonomyNode,
    TaxonomyOccurrence,
    _walk_leaves,
)


@dataclass(frozen=True)
class Taxonomy:
    """Parsed MQDA coding taxonomy.

    ``Taxonomy`` is the side-effect-free representation of the source
    taxonomy. Its methods answer questions about hierarchy, special
    categories, and label validity; they do not know how concepts are stored
    remotely. :mod:`taxonomy_import` consumes this representation when it
    needs to create records and resolve their IDs.

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
    occurrences: tuple[TaxonomyOccurrence, ...] = ()
    categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    sub_categories: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    concept_to_category: dict[str, str] = field(default_factory=dict, init=False)
    _zeitangaben_data: list[Timespan] = field(default_factory=list, init=False)
    _personae_data: list[str] = field(default_factory=list, init=False)
    _go_data: list[str] = field(
        default_factory=list, init=False
    )  # Will be built at method call time

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
        categories = {
            k: v for k, v in self.categories.items() if k not in special_categories
        }

        # Remove from sub_categories (those with parent in special categories)
        sub_categories = {
            k: v
            for k, v in self.sub_categories.items()
            if v.get("parent") not in special_categories
        }

        # Remove from concept_to_category (those pointing to special categories)
        concept_to_category = {
            label: cat
            for label, cat in self.concept_to_category.items()
            if cat not in special_categories
        }

        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "sub_categories", sub_categories)
        object.__setattr__(self, "concept_to_category", concept_to_category)

    def zeitangaben(self) -> list[Timespan]:
        """Return all leaf concepts under the Zeitangaben category as Timespan objects.

        Returns pre-extracted data.

        >>> from taxonomy import load_taxonomy
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

        >>> from taxonomy import load_taxonomy
        >>> tax = load_taxonomy()
        >>> people = tax.personae()
        >>> 'Burgheim, Hedwig' in people
        True
        >>> len(people) > 0
        True
        """
        return self._personae_data

    def validate_unique_labels(self) -> None:
        """Reject repeated labels within one top-level taxonomy category.

        Labels may intentionally occur in different top-level categories, so
        the import identity is scoped by the root category. This check runs
        before :mod:`taxonomy_import` can perform any API writes.
        """
        if self.occurrences:
            seen_by_top_level: dict[str, dict[str, tuple[str, ...]]] = {}
            for occurrence in self.occurrences:
                top_level = _label_key(_extract_key(occurrence.top_level))
                seen = seen_by_top_level.setdefault(top_level, {})
                label_key = _label_key(occurrence.label)
                if label_key in seen:
                    previous = " > ".join(seen[label_key])
                    current = " > ".join(occurrence.path)
                    raise TaxonomyError(
                        f"Label {occurrence.label!r} occurs twice in top-level "
                        f"category {occurrence.top_level!r}: {previous!r} and "
                        f"{current!r}"
                    )
                seen[label_key] = occurrence.path
            return

        seen_by_top_level: dict[str, dict[str, tuple[str, ...]]] = {}
        for root_label in self.hierarchy.get(ROOT_KEY, []):
            top_level = _label_key(_extract_key(root_label))
            seen = seen_by_top_level.setdefault(top_level, {})

            def visit(label: str, path: tuple[str, ...]) -> None:
                clean_label = label.strip()
                label_key = _label_key(clean_label)
                if label_key in seen:
                    previous = " > ".join(seen[label_key])
                    current = " > ".join(path)
                    raise TaxonomyError(
                        f"Label {clean_label!r} occurs twice in top-level "
                        f"category {root_label!r}: {previous!r} and {current!r}"
                    )
                seen[label_key] = path
                for child in self.hierarchy.get(label, []):
                    visit(child, path + (child.strip(),))

            visit(root_label, (root_label.strip(),))

    def concept_nodes(self) -> list[TaxonomyNode]:
        """Return validated hierarchy nodes for :mod:`taxonomy_import`.

        The returned keys identify taxonomy paths, not database primary keys;
        assigning and reusing those IDs is the importer module's job.
        """
        self.validate_unique_labels()
        nodes: list[TaxonomyNode] = []

        if self.occurrences:
            keys_by_index: dict[int, tuple[str, ...]] = {}
            for index, occurrence in enumerate(self.occurrences):
                top_level_key = _label_key(_extract_key(occurrence.top_level))
                node_key = (top_level_key,) + tuple(
                    _label_key(part) for part in occurrence.path
                )
                parent_key = (
                    keys_by_index[occurrence.parent_index]
                    if occurrence.parent_index is not None
                    else None
                )
                icon = ""
                if parent_key is None:
                    icon = ROOT_ICONS.get(
                        _extract_key(occurrence.label),
                        ROOT_ICONS.get(occurrence.label, ""),
                    )
                nodes.append(
                    TaxonomyNode(
                        key=node_key,
                        label=occurrence.label,
                        parent_key=parent_key,
                        top_level=occurrence.top_level,
                        icon=icon,
                    )
                )
                keys_by_index[index] = node_key
            return nodes

        def visit(
            label: str,
            top_level: str,
            top_level_key: str,
            parent_key: tuple[str, ...] | None,
            path: tuple[str, ...],
        ) -> None:
            clean_label = label.strip()
            node_key = (top_level_key,) + tuple(_label_key(part) for part in path)
            icon = ""
            if parent_key is None:
                icon = ROOT_ICONS.get(
                    _extract_key(clean_label), ROOT_ICONS.get(clean_label, "")
                )
            nodes.append(
                TaxonomyNode(
                    key=node_key,
                    label=clean_label,
                    parent_key=parent_key,
                    top_level=top_level,
                    icon=icon,
                )
            )
            for child in self.hierarchy.get(label, []):
                visit(child, top_level, top_level_key, node_key, path + (child,))

        for root_label in self.hierarchy.get(ROOT_KEY, []):
            top_level_key = _label_key(_extract_key(root_label))
            visit(
                root_label,
                root_label.strip(),
                top_level_key,
                None,
                (root_label.strip(),),
            )
        return nodes

    def import_aliases(self) -> dict[str, tuple[str, ...]]:
        """Return normalized source aliases for the import layer.

        This only maps source vocabulary to taxonomy path keys. It does not
        resolve those keys to API/database IDs; :class:`taxonomy_import.TaxonomyImport`
        performs that second step after records exist.
        """
        aliases = {
            "alte_heimat": ("alte Heimat", None),
            "neue_heimat": ("neue Heimat", None),
            "reise_zurueck": ("Reise zurück", None),
            "ort_der_zeit": ("OZ – Orte der Zeit", None),
            "erinnerungsort": ("EO – Erinnerungsorte", None),
            "verkehrsmittel": ("VM – Verkehr & Bewegungsräume", None),
            "birth": ("Geburt", "LL"),
            "death": ("Tod", "LL"),
            "arrest": ("Verhaftung", "LL"),
            "emigration": ("Auswanderung", "LL"),
            "immigration": ("Einwanderung (Endstation)", "LL"),
            "marriage": ("Heirat", "LL"),
            "residence": ("Wohnung / Wohnort", "SR"),
            "train": ("Zug", "VM"),
            "ship": ("Schiff", "VM"),
            "work": ("Beruf", "LL"),
            "english": ("Englisch", "Sprache(n)"),
        }
        nodes = self.concept_nodes()
        nodes_by_label = {}
        for node in nodes:
            nodes_by_label.setdefault(_label_key(node.label), []).append(node)
        result: dict[str, tuple[str, ...]] = {}
        for source, (target, top_level) in aliases.items():
            candidates = nodes_by_label.get(_label_key(target), [])
            if top_level is not None:
                candidates = [
                    node
                    for node in candidates
                    if _label_key(_extract_key(node.top_level)) == _label_key(top_level)
                ]
            if len(candidates) == 1:
                result[_label_key(source)] = candidates[0].key
        return result

    def go(self) -> list[dict[str, str]]:
        """Return leaf geographic locations with compiled hierarchical paths.

        Returns pre-extracted data.

        >>> from taxonomy import load_taxonomy
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
            main_label = (
                concept_label.split(" ")[0] if " " in concept_label else concept_label
            )
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
            k: v
            for k, v in self.sub_categories.items()
            if v.get("parent") != category_key and k.split("__")[0] != category_key
        }
        object.__setattr__(self, "sub_categories", new_sub_categories)

        # Remove from concept_to_category
        new_concept_to_category = {
            label: cat
            for label, cat in self.concept_to_category.items()
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

    def _build_concept_labels_with_context(self, category_key: str) -> list[str]:
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
                first_parent = (
                    node  # First-level children become the context for deeper nodes
                )

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
