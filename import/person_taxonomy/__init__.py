"""Merge reviewed person names and metadata into the Personae concept tree.

Several importers match people by name: the metadati and person biography
imports, the API client, the taxonomy importer, and the data validator. They
share one normalization, one reviewed synonym table, and one set of Personae
helpers, so a person is matched the same way wherever a name appears. This
package holds all three. It makes no API calls and writes no files. The taxonomy
writes happen in ``taxonomy_import``, which receives the results.

Production code outside the package imports from ``person_taxonomy`` itself.
The main entry point is ``augment_personae_taxonomy``, which the chronotopi
notebook calls before the taxonomy import::

    from person_taxonomy import augment_personae_taxonomy

    augmentation = augment_personae_taxonomy(taxonomy, overview, data_root=root)
    taxonomy = augmentation.taxonomy
    person_aliases = augmentation.aliases

The submodules are ``keys`` (normalization and placeholders), ``model`` (error
and value types), ``synonyms`` (loading the reviewed JSON), ``names`` (lookups
and name variants), ``hierarchy`` (Personae tree helpers), and ``augment`` (the
merge). Underscore names are re-exported for other import modules such as
``validate_data``; they are internal helpers, not a stable API.
"""

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
