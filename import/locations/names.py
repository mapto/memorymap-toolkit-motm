"""Normalize location names and find their canonical workbook entity.

One place appears in many sources with different case, punctuation, word order,
parenthetical qualifiers, and reviewed aliases. Without a shared key, each
spelling would create its own API LocationPoint. ``normalize_location`` gives
every spelling one matching key, and ``canonical_location_name`` maps a source
label to the name of the workbook row that represents the place.

Neither function writes files or makes requests. ``db``, ``entities``, and
``rebuild_locations`` call ``normalize_location``, and ``entities`` also calls
``canonical_location_name``.
"""

import regex as re
from locations.synonyms import taxonomy_alias, taxonomy_reviewed_unmapped


def canonical_location_name(value, locations_db=None):
    """Map a source location spelling to one workbook entity when possible.

    Returns None for blank labels, URLs, and labels the reviewed table lists as
    not locations, so no entity is created for them. Without ``locations_db``,
    the cleaned label is returned. With it, the reviewed alias and the label are
    each tried, with parenthetical qualifiers removed in turn, against the
    workbook keys and then against record names and their aliases. The last
    attempt picks the longest record name whose words all appear in the label.
    If nothing matches, the cleaned label is returned. ``entities`` calls this
    before it looks up a name.
    """
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
    """Normalize a location name for matching.

    Case is folded, hyphens and underscores become spaces, remaining punctuation
    is removed, and the words are sorted, so names that differ only in case,
    punctuation, or word order share one key. The key is the dictionary key of
    the in-memory workbook database, and it is what API location names are
    compared against.

    >>> normalize_location("Frankfurt-Main")
    'frankfurt main'
    """
    name = str(name).strip().casefold()
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(sorted(name.split()))
