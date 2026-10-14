"""Error and value types for person taxonomy synonyms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from person_taxonomy.keys import person_taxonomy_key


class PersonTaxonomyError(ValueError):
    """Raised when source person labels cannot be mapped unambiguously."""


@dataclass(frozen=True)
class PersonName:
    """A person's family and given names, as written in a 'Surname, Given' label."""

    family_name: str
    given_name: str

    @classmethod
    def from_label(cls, label: str) -> PersonName | None:
        """Parse a 'Surname, Given' label; return None when it has no comma."""
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

    The mappings are read-only; copy them before changing anything.
    """

    aliases: Mapping[str, str]
    metadata_by_chronotopi: Mapping[str, str]
    metadata_relatives: Mapping[str, Mapping[str, PersonName]]

    def canonical_label(self, value: str) -> str | None:
        """Return the reviewed canonical Personae label for a source name."""
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

        Links are scoped to one workbook, because the same relation text can name
        different people in different families.
        """
        if not metadata_source:
            return None
        links = self.metadata_relatives.get(Path(str(metadata_source)).name, {})
        return links.get(person_taxonomy_key(relation))
