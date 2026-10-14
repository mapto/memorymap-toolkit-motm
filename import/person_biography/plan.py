"""Building the person biography import plan from workbooks."""

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

    The workbook association in ``person_taxonomy_synonyms.json`` is the
    authority for metadata matching. No API calls or workbook writes occur.
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
