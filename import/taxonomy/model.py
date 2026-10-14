"""Taxonomy data types, category icons, and tree walkers."""

from __future__ import annotations

from dataclasses import dataclass


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


class TaxonomyError(ValueError):
    """Raised when the source taxonomy cannot provide stable concept IDs."""


@dataclass(frozen=True)
class TaxonomyNode:
    """One taxonomy occurrence with a stable, top-level-scoped identity."""

    key: tuple[str, ...]
    label: str
    parent_key: tuple[str, ...] | None
    top_level: str
    icon: str = ""


@dataclass(frozen=True)
class TaxonomyOccurrence:
    """One source-tree occurrence, retaining its path and parent occurrence."""

    label: str
    parent_index: int | None
    top_level: str
    path: tuple[str, ...]


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
