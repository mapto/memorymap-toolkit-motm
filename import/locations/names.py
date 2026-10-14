"""Location name normalization and canonical lookup."""

import regex as re
from locations.synonyms import taxonomy_alias, taxonomy_reviewed_unmapped


def canonical_location_name(value, locations_db=None):
    """Map a source location spelling to one workbook entity when possible."""
    cleaned = str(value or "").strip()
    if not cleaned or taxonomy_reviewed_unmapped(cleaned) or cleaned.startswith("http"):
        return None
    if locations_db is None:
        return cleaned

    candidates = []
    for seed in (taxonomy_alias(cleaned), cleaned):
        candidate = seed
        while candidate:
            if candidate not in candidates:
                candidates.append(candidate)
            if not re.search(r"\([^()]*\)", candidate):
                break
            candidate = re.sub(r"\s*\([^()]*\)", "", candidate).strip()

    for candidate in candidates:
        key = normalize_location(candidate)
        if key in locations_db:
            return locations_db[key].get("name", candidate)

    candidate_keys = {normalize_location(candidate) for candidate in candidates}
    for record in locations_db.values():
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        record_keys = {
            normalize_location(name),
            normalize_location(taxonomy_alias(name)),
        }
        if candidate_keys & record_keys:
            return name

    source_tokens = set(normalize_location(cleaned).split())
    matching = []
    for record in locations_db.values():
        name = record.get("name", "")
        tokens = set(normalize_location(name).split())
        if tokens and tokens <= source_tokens:
            matching.append((len(tokens), name))
    if matching:
        return max(matching)[1]
    return cleaned


def normalize_location(name):
    """Normalize a location name for matching: lowercase, no punctuation, sorted words."""
    name = str(name).strip().casefold()
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(sorted(name.split()))
