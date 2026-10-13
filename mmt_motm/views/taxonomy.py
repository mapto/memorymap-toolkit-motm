import json
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import Count

from ..models import Concept, LocationPoint


def _build_concept_taxonomy_tree(language_code):
    """Build one shared concept/location tree for both taxonomy pages.

    Every concept has ``taxonomy_children``; GO concepts additionally have
    their attached or safely matched LocationPoints. Using one builder keeps
    the GO branch on the concept taxonomy page identical to the locations
    taxonomy page.
    """
    concepts = list(
        Concept.objects.active_translations(language_code)
        .order_by("id")
    )
    concepts_by_parent = {}
    for concept in concepts:
        concepts_by_parent.setdefault(concept.parent_id, []).append(concept)
        concept.taxonomy_children = []
        concept.location_points = []
        concept.location_link = None
    for concept in concepts:
        concept.taxonomy_children = concepts_by_parent.get(concept.pk, [])

    roots = concepts_by_parent.get(None, [])
    go_root = next(
        (
            concept
            for concept in roots
            if _location_taxonomy_key(concept.label)
            == _location_taxonomy_key("GO – geographischer Ort")
        ),
        None,
    )
    if go_root is None:
        return roots, None, set()

    go_ids = set()
    pending = [go_root.pk]
    while pending:
        parent_id = pending.pop()
        if parent_id in go_ids:
            continue
        go_ids.add(parent_id)
        pending.extend(
            child.pk for child in concepts_by_parent.get(parent_id, [])
        )
    go_nodes = [concept for concept in concepts if concept.pk in go_ids]

    points_by_concept = {}
    for point in LocationPoint.objects.filter(
        concept_id__in=go_ids
    ).order_by("current_name"):
        points_by_concept.setdefault(point.concept_id, []).append(point)

    matchable_nodes = sorted(
        (concept for concept in go_nodes if concept.pk != go_root.pk),
        key=lambda concept: len(_location_taxonomy_key(concept.label)),
        reverse=True,
    )
    matched_orphans = set()
    for point in (
        LocationPoint.objects.filter(concept__isnull=True)
        .select_related("region")
        .order_by("current_name")
    ):
        match = _match_location_to_go_concept(point, matchable_nodes)
        if match:
            points_by_concept.setdefault(match.pk, []).append(point)
            matched_orphans.add(point.pk)

    go_nodes_by_id = {concept.pk: concept for concept in go_nodes}
    for concept_id, points in points_by_concept.items():
        concept = go_nodes_by_id.get(concept_id)
        if concept is None:
            continue
        concept.location_points = sorted(
            points,
            key=lambda point: point.current_name.casefold(),
        )
        concept.location_link = next(
            (
                point
                for point in concept.location_points
                if _location_taxonomy_key(point.current_name)
                == _location_taxonomy_key(concept.label)
            ),
            None,
        )
    return roots, go_root, matched_orphans


def _location_taxonomy_key(value):
    """Normalize location labels for safe GO-tree matching."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(value or "").casefold()).split())


@lru_cache(maxsize=1)
def _location_taxonomy_synonym_data():
    path = Path(str(settings.BASE_DIR)) / "data" / "location_taxonomy_synonyms.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["aliases"] = {
        _location_taxonomy_key(source): target
        for source, target in data.get("aliases", {}).items()
    }
    data["excluded_contains"] = [
        _location_taxonomy_key(value)
        for value in data.get("excluded_contains", [])
    ]
    return data


def _location_taxonomy_alias(value):
    key = _location_taxonomy_key(value)
    return _location_taxonomy_synonym_data()["aliases"].get(key, value)


def _location_taxonomy_match_excluded(value):
    key = _location_taxonomy_key(value)
    return any(
        term in key
        for term in _location_taxonomy_synonym_data()["excluded_contains"]
    )


def _location_point_for_concept(concept):
    location = LocationPoint.objects.filter(concept=concept).first()
    if location:
        return location

    root = concept
    while root.parent_id is not None:
        root = root.parent
    if _location_taxonomy_key(root.label) != _location_taxonomy_key(
        "GO – geographischer Ort"
    ):
        return None

    label_key = _location_taxonomy_key(concept.label)
    if not label_key or _location_taxonomy_match_excluded(label_key):
        return None
    return next(
        (
            point
            for point in LocationPoint.objects.filter(concept__isnull=True)
            .only("pk", "current_name")
            .order_by("current_name", "pk")
            if _location_taxonomy_key(point.current_name) == label_key
        ),
        None,
    )


def _match_location_to_go_concept(point, candidates):
    """Find the most specific GO concept matching an orphan location point."""
    if _location_taxonomy_match_excluded(point.current_name):
        return None
    names = [
        _location_taxonomy_key(point.current_name),
        _location_taxonomy_key(_location_taxonomy_alias(point.current_name)),
    ]
    if point.region_id and point.region:
        names.append(_location_taxonomy_key(point.region.name))
    for candidate in candidates:
        label = _location_taxonomy_key(candidate.label)
        if not label:
            continue
        if any(
            name == label or re.search(rf"(?:^| ){re.escape(label)}(?: |$)", name)
            for name in names
        ):
            return candidate
    return None