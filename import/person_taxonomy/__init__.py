"""Merge reviewed person names and metadata into the Personae concept tree."""

from person_taxonomy.keys import (
    _NAME_PLACEHOLDERS,
    person_taxonomy_key,
    _clean_name,
    is_placeholder_name,
)

from person_taxonomy.model import (
    PersonTaxonomyError,
    PersonName,
    PersonTaxonomySynonyms,
)

from person_taxonomy.synonyms import (
    PERSON_TAXONOMY_SYNONYMS_PATH,
    _read_person_taxonomy_synonyms,
    load_person_taxonomy_synonyms,
)

from person_taxonomy.names import (
    metadata_relative_name,
    person_taxonomy_alias,
    canonical_person_name,
    _metadata_name_variants,
    _existing_person_variants,
)

from person_taxonomy.hierarchy import (
    _occurrences_for,
    _hierarchy_from_occurrences,
    _parent_first_occurrences,
    _is_personae_occurrence,
    _is_collective_label,
)

from person_taxonomy.augment import (
    PersonaeAugmentation,
    _SourceBranch,
    augment_personae_taxonomy,
)

__all__ = [
    "_NAME_PLACEHOLDERS",
    "person_taxonomy_key",
    "_clean_name",
    "is_placeholder_name",
    "PersonTaxonomyError",
    "PersonName",
    "PersonTaxonomySynonyms",
    "PERSON_TAXONOMY_SYNONYMS_PATH",
    "_read_person_taxonomy_synonyms",
    "load_person_taxonomy_synonyms",
    "metadata_relative_name",
    "person_taxonomy_alias",
    "canonical_person_name",
    "_metadata_name_variants",
    "_existing_person_variants",
    "_occurrences_for",
    "_hierarchy_from_occurrences",
    "_parent_first_occurrences",
    "_is_personae_occurrence",
    "_is_collective_label",
    "PersonaeAugmentation",
    "_SourceBranch",
    "augment_personae_taxonomy",
]
