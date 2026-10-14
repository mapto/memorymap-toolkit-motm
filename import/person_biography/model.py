"""Error types and mutable biography records."""

from __future__ import annotations

from dataclasses import dataclass, field
from timespan import Timespan


class PersonBiographyError(ValueError):
    """Raised when biography sources cannot be associated or imported safely."""


class PersonBiographyConflictError(PersonBiographyError):
    """Raised when metadata, chronotopi, or existing Person values disagree."""

    def __init__(self, conflicts):
        self.conflicts = tuple(conflicts)
        details = "\n".join(f"- {conflict}" for conflict in self.conflicts)
        super().__init__(f"Person biography conflicts detected:\n{details}")


@dataclass(frozen=True)
class PersonBiography:
    """Validated biography values ready to merge into a Person record."""

    person_name: str
    identity_key: str
    birth_span: Timespan | None = None
    birth_place: str | None = None
    death_span: Timespan | None = None
    death_place: str | None = None
    metadata_birth_span: Timespan | None = None
    metadata_birth_place: str | None = None
    metadata_death_span: Timespan | None = None
    metadata_death_place: str | None = None
    source_workbooks: tuple[str, ...] = ()

    @property
    def birth_date(self) -> str | None:
        return self.birth_span.start.isoformat() if self.birth_span else None

    @property
    def death_date(self) -> str | None:
        return self.death_span.start.isoformat() if self.death_span else None


@dataclass
class _MutableBiography:
    person_name: str
    identity_key: str
    birth_span: Timespan | None = None
    birth_place: str | None = None
    death_span: Timespan | None = None
    death_place: str | None = None
    metadata_birth_span: Timespan | None = None
    metadata_birth_place: str | None = None
    metadata_death_span: Timespan | None = None
    metadata_death_place: str | None = None
    source_workbooks: set[str] = field(default_factory=set)
    has_biographical_event: bool = False
