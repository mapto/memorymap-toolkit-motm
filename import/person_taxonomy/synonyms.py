"""Loading the reviewed person synonym table.

``data/person_taxonomy_synonyms.json`` records, after manual review, how source
spellings map to Personae labels, which chronotopi workbook belongs to which
metadati workbook, and which unnamed relatives are which people. This module
parses and validates that file into a ``PersonTaxonomySynonyms``. Validation is
strict on purpose: a bad entry stops the import with a message that names it,
rather than being dropped silently, which would leave a spelling unmatched.

The importers call ``load_person_taxonomy_synonyms``, so they share one parsed
copy. Parsing is cached per resolved path, so a change to the JSON is not seen
by a process that has already loaded it. Tests pass a temporary file path
instead of the repository copy.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from person_taxonomy.keys import person_taxonomy_key, _clean_name
from person_taxonomy.model import (
    PersonTaxonomyError,
    PersonName,
    PersonTaxonomySynonyms,
)


PERSON_TAXONOMY_SYNONYMS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "person_taxonomy_synonyms.json"
)


@lru_cache(maxsize=8)
def _read_person_taxonomy_synonyms(path: str) -> PersonTaxonomySynonyms:
    """Parse and validate one synonym JSON file, caching the result by path.

    The file must hold a JSON object. Alias sources are normalized to match keys,
    and targets are cleaned. Two entries that map one source to different targets
    are rejected, because matching would then be ambiguous. Metadata relative
    targets must be ``Surname, Given`` labels. Invalid entries raise
    ``PersonTaxonomyError`` naming the entry, and malformed JSON raises
    ``json.JSONDecodeError``. Failed calls are not cached, so a corrected file is
    read on the next call.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PersonTaxonomyError("Person taxonomy synonym data must be a JSON object")

    aliases: dict[str, str] = {}
    for source, target in data.get("aliases", {}).items():
        source_key = person_taxonomy_key(source)
        target_label = _clean_name(target)
        if not source_key or not target_label:
            raise PersonTaxonomyError(
                f"Person synonym entries need non-empty source and target: {source!r}"
            )
        previous = aliases.get(source_key)
        if previous and person_taxonomy_key(previous) != person_taxonomy_key(
            target_label
        ):
            raise PersonTaxonomyError(
                f"Conflicting person aliases for {source!r}: {previous!r} and "
                f"{target_label!r}"
            )
        aliases[source_key] = target_label

    metadata_by_chronotopi = {
        Path(source).name: Path(metadata).name
        for source, metadata in data.get("metadata_by_chronotopi", {}).items()
    }
    metadata_relatives: dict[str, dict[str, PersonName]] = {}
    for workbook, links in data.get("metadata_relatives", {}).items():
        relative_names: dict[str, PersonName] = {}
        for relation, target in links.items():
            relation_key = person_taxonomy_key(relation)
            name = PersonName.from_label(_clean_name(target))
            if not relation_key or name is None:
                raise PersonTaxonomyError(
                    "Metadata relative links need a relation and a 'Surname, Given' "
                    f"target: {relation!r} -> {target!r}"
                )
            relative_names[relation_key] = name
        metadata_relatives[Path(workbook).name] = relative_names
    return PersonTaxonomySynonyms(
        aliases=MappingProxyType(aliases),
        metadata_by_chronotopi=MappingProxyType(metadata_by_chronotopi),
        metadata_relatives=MappingProxyType(
            {
                workbook: MappingProxyType(names)
                for workbook, names in metadata_relatives.items()
            }
        ),
    )


def load_person_taxonomy_synonyms(path=None) -> PersonTaxonomySynonyms:
    """Load aliases, chronotopi-to-metadata associations and relative links."""
    source_path = Path(path or PERSON_TAXONOMY_SYNONYMS_PATH).resolve()
    return _read_person_taxonomy_synonyms(str(source_path))
