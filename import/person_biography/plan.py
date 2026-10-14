"""Building the person biography import plan from workbooks.

This is the plan step. It reads the chronotopi events, the chronotopi overview of
workbooks and sheets, the metadati person workbooks, and the reviewed person
synonyms file, and returns one ``PersonBiography`` per identity key. It makes no
API calls and writes no files. The notebook calls it before the validate and
apply steps. ``validate_data.py`` calls it to report source problems without
changing anything.

Sheets with no birth or death event are left out. Most source disagreements are
collected and raised together as ``PersonBiographyConflictError``. Configuration
problems, such as a missing metadati workbook, raise ``PersonBiographyError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
from person_taxonomy import load_person_taxonomy_synonyms
from person_biography.model import (
    PersonBiographyError,
    PersonBiographyConflictError,
    PersonBiography,
    _MutableBiography,
)
from person_biography.identity import _clean_name, _identity_from_name
from person_biography.sources import (
    _collect_sheet_facts,
    _rows_for_sheet,
    _basename,
    _metadata_for_workbook,
)
from person_biography.merge import _combine_source_facts, _merge_biographies


def build_person_biography_plan(
    overview: Mapping[str, list[str] | tuple[str, ...]],
    dataframe,
    data_root: str | Path,
    *,
    synonyms_path: str | Path | None = None,
) -> dict[str, PersonBiography]:
    """Build and validate a source-only Person biography import plan.

    This is the plan step. It makes no API calls and writes nothing, so a
    disagreement stops the run before any record changes. Each chronotopi sheet
    is read for birth and death events, checked against the metadati workbook
    that the synonyms file names for its chronotopi workbook, and merged with any
    other sheet for the same person. The workbook association in
    ``person_taxonomy_synonyms.json`` is the authority for metadata matching.

    Args:
        overview: Maps each chronotopi workbook path to its sheet titles. Each
            sheet is one person.
        dataframe: Chronotopi event rows as a pandas DataFrame. The optional
            ``name`` and ``source_workbook`` columns select one sheet's rows.
        data_root: Folder that holds the metadati workbooks named in the synonyms
            file.
        synonyms_path: Synonyms JSON to read. The reviewed default is used when
            None.

    Returns:
        A dict from identity key to ``PersonBiography``. Sheets with no birth or
        death event are omitted.

    Raises:
        PersonBiographyError: A chronotopi workbook has no metadata workbook
            configured, the configured one is missing, or a sheet title appears in
            two workbooks without a ``source_workbook`` column.
        PersonBiographyConflictError: Sources disagree about a date or a place.
    """
    config = load_person_taxonomy_synonyms(synonyms_path)
    aliases = config.aliases
    source_root = Path(data_root).resolve()
    plan: dict[str, _MutableBiography] = {}
    conflicts: list[str] = []

    source_owners: dict[str, str] = {}
    has_source_workbook_column = "source_workbook" in getattr(dataframe, "columns", ())
    for workbook_path, sheet_names in sorted(overview.items()):
        workbook_name = _basename(workbook_path)
        metadata_name = config.metadata_workbook_for(workbook_name)
        if not metadata_name:
            raise PersonBiographyError(
                f"No metadata workbook is configured for chronotopi source "
                f"{workbook_name!r}"
            )
        metadata_path = source_root / metadata_name
        if not metadata_path.is_file():
            raise PersonBiographyError(
                f"Metadata workbook for {workbook_name!r} was not found: "
                f"{metadata_path}"
            )
        metadata_people = _metadata_for_workbook(metadata_path, aliases)

        for sheet_name in sheet_names:
            cleaned_sheet = _clean_name(sheet_name)
            if not cleaned_sheet or cleaned_sheet.startswith("_"):
                continue
            previous_owner = source_owners.get(cleaned_sheet)
            if (
                previous_owner
                and previous_owner != workbook_name
                and not has_source_workbook_column
            ):
                raise PersonBiographyError(
                    f"Chronotopi sheet {cleaned_sheet!r} appears in multiple "
                    "workbooks; add a source_workbook column before validating"
                )
            source_owners[cleaned_sheet] = workbook_name

            rows = _rows_for_sheet(dataframe, workbook_name, cleaned_sheet)
            identity_key = _identity_from_name(cleaned_sheet, aliases)
            source_label = f"{workbook_name} / {cleaned_sheet}"
            facts = _collect_sheet_facts(
                cleaned_sheet,
                identity_key,
                rows,
                source_label,
                conflicts,
            )
            if not facts.has_biographical_event:
                continue

            metadata = metadata_people.get(identity_key)
            facts = _combine_source_facts(
                facts,
                metadata,
                metadata_name,
                conflicts,
            )
            if identity_key in plan:
                _merge_biographies(plan[identity_key], facts, conflicts)
            else:
                plan[identity_key] = facts

    if conflicts:
        raise PersonBiographyConflictError(conflicts)

    return {
        identity: PersonBiography(
            person_name=facts.person_name,
            identity_key=identity,
            birth_span=facts.birth_span,
            birth_place=facts.birth_place,
            death_span=facts.death_span,
            death_place=facts.death_place,
            metadata_birth_span=facts.metadata_birth_span,
            metadata_birth_place=facts.metadata_birth_place,
            metadata_death_span=facts.metadata_death_span,
            metadata_death_place=facts.metadata_death_place,
            source_workbooks=tuple(sorted(facts.source_workbooks)),
        )
        for identity, facts in plan.items()
    }


def _plan_values(plan):
    return list(plan.values()) if isinstance(plan, Mapping) else list(plan)
