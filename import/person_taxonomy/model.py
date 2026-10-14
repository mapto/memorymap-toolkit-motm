"""Error and value types for person taxonomy synonyms.

These types are the shared vocabulary of the person import. ``PersonTaxonomyError``
signals that source names cannot be mapped to one person. ``validate_data.py``
catches it and records it in the validation report, so one ambiguous name does
not end the whole check. ``PersonName`` holds a reviewed name as
``Surname, Given``, the form Personae leaves use, and renders it as
``Given Surname``, the form sheet names use. ``PersonTaxonomySynonyms`` is the
loaded, read-only view of the synonym JSON. ``synonyms`` builds one per file,
and the lookups in ``names`` and ``augment`` query it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from person_taxonomy.keys import person_taxonomy_key


class PersonTaxonomyError(ValueError):
    """Raised when source person labels cannot be mapped unambiguously."""


@dataclass(frozen=True)
class PersonName:
    """A person's family and given names, as written in a 'Surname, Given' label.

    Personae leaves are stored as ``Surname, Given``, while sheet names use
    ``Given Surname``. This value object keeps the two parts once, so both
    spellings are derived rather than stored separately. Instances are immutable
    and compare equal when both parts match.
    """

    family_name: str
    given_name: str

    @classmethod
    def from_label(cls, label: str) -> PersonName | None:
        """Parse a 'Surname, Given' label, or return None when it has no comma.

        Only the first comma separates the two parts, so a given name may contain
        further commas. The parts are stripped but not otherwise validated, so an
        empty part is possible when this is called directly. The synonym loader
        cleans labels first and rejects those without a comma.
        """
        if "," not in label:
            return None
        family_name, given_name = (part.strip() for part in label.split(",", 1))
        return cls(family_name=family_name, given_name=given_name)

    @property
    def label(self) -> str:
        """The reviewed Personae form, 'Surname, Given'."""
        return f"{self.family_name}, {self.given_name}"

    @property
    def natural_order(self) -> str:
        """The sheet and metadata form, 'Given Surname'."""
        return f"{self.given_name} {self.family_name}"

    def variants(self) -> list[str]:
        """Source spellings that refer to this person."""
        return [self.natural_order, self.label]


@dataclass(frozen=True)
class PersonTaxonomySynonyms:
    """Reviewed person aliases and metadata links from the synonyms JSON.

    ``synonyms`` builds one instance per file, and the methods here answer the
    questions the importers ask: which Personae label a spelling means, which
    metadata workbook belongs to a chronotopi workbook, and who an unnamed
    relative is within one workbook. The mappings are read-only proxies shared
    by every caller, so copy them before changing anything.
    """

    aliases: Mapping[str, str]
    metadata_by_chronotopi: Mapping[str, str]
    metadata_relatives: Mapping[str, Mapping[str, PersonName]]

    def canonical_label(self, value: str) -> str | None:
        """Return the reviewed Personae label for a source spelling, or None.

        An explicit alias wins. Otherwise the value matches a reviewed label in
        either its ``Surname, Given`` or ``Given Surname`` form, compared with the
        same key normalization used for aliases. None means the table has no
        entry, and callers fall back to the source name.
        """
        key = person_taxonomy_key(value)
        target = self.aliases.get(key)
        if target:
            return target
        for canonical in self.aliases.values():
            if key == person_taxonomy_key(canonical):
                return canonical
            name = PersonName.from_label(canonical)
            if name is not None and key == person_taxonomy_key(name.natural_order):
                return canonical
        return None

    def metadata_workbook_for(self, chronotopi_source: str | Path) -> str | None:
        """Return the metadata workbook reviewed for a chronotopi workbook."""
        return self.metadata_by_chronotopi.get(Path(str(chronotopi_source)).name)

    def metadata_relative_name(
        self, metadata_source: str | Path | None, relation: str
    ) -> PersonName | None:
        """Return the reviewed person for an unnamed relative of one workbook.

        ``metadati.relationships.create_relationship`` calls this when a relative's
        given name is a placeholder, and uses the result in place of the
        placeholder names. Links are scoped to one workbook, because the same
        relation text can name different people in different families. Returns
        None when there is no metadata source or no link for the relation, so the
        placeholder is kept.
        """
        if not metadata_source:
            return None
        links = self.metadata_relatives.get(Path(str(metadata_source)).name, {})
        return links.get(person_taxonomy_key(relation))
