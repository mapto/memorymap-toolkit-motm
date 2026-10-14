"""Error types and mutable biography records.

``PersonBiographyError`` and ``PersonBiographyConflictError`` are raised by the
plan, validate, and apply steps. ``_MutableBiography`` is the working record that
the plan step builds while it reads sheets and workbooks. ``PersonBiography`` is
the frozen result of the plan, and the validate and apply steps only read it.
This module does no file or API work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from timespan import Timespan


class PersonBiographyError(ValueError):
    """Raised when biography sources cannot be associated or imported safely.

    The plan step raises it for input problems: a chronotopi workbook with no
    configured metadata workbook, a configured metadata workbook that is missing,
    a sheet title that appears in two workbooks without a ``source_workbook``
    column, or events that are not a dataframe. The apply step raises it when a
    Person cannot be read back. ``PersonBiographyConflictError`` is a subclass, so
    one ``except PersonBiographyError`` clause catches both.
    """


class PersonBiographyConflictError(PersonBiographyError):
    """Raised when metadata, chronotopi, or existing Person values disagree.

    ``conflicts`` keeps the messages as a tuple, and ``str()`` lists them one per
    line, so a reviewer can fix every clash in one pass. The plan step raises it
    once every source has been read. The family-metadata reader in ``sources``
    raises it at once for a conflicting relative. The apply and validate steps
    raise it for a stored Person value that does not match the plan.
    """

    def __init__(self, conflicts):
        self.conflicts = tuple(conflicts)
        details = "\n".join(f"- {conflict}" for conflict in self.conflicts)
        super().__init__(f"Person biography conflicts detected:\n{details}")


@dataclass(frozen=True)
class PersonBiography:
    """Validated biography values ready to merge into a Person record.

    The plan step returns one instance per identity key. The validate and apply
    steps read ``birth_span``, ``death_span``, and the place names. The
    ``metadata_*`` fields hold the metadati values for the same person, so the
    apply step can tell a year-level metadata start from an exact stored date.
    ``source_workbooks`` holds ``workbook / sheet`` labels for each contributing
    sheet. ``birth_date`` and ``death_date`` give the ISO start day, or None.
    The record is frozen, so build a new one instead of assigning a field.
    """

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
        start = self.birth_span.start if self.birth_span else None
        return start.isoformat() if start is not None else None

    @property
    def death_date(self) -> str | None:
        start = self.death_span.start if self.death_span else None
        return start.isoformat() if start is not None else None


@dataclass
class _MutableBiography:
    """Hold one person's facts while the plan step is still combining them.

    ``_collect_sheet_facts`` creates one instance per chronotopi sheet. Metadati
    values are added by ``_combine_source_facts``, and a repeated person is folded
    in by ``_merge_biographies``. ``has_biographical_event`` is set when a sheet
    has at least one birth or death row, and sheets without one are dropped from
    the plan. The plan step converts each instance to a frozen
    ``PersonBiography``, so this mutable form never reaches the later steps.
    """

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
