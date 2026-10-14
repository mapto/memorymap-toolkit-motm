"""Classifying and collecting facts from sheets and metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from utils import clean_str
from person_biography.model import (
    PersonBiographyError,
    PersonBiographyConflictError,
    _MutableBiography,
)
from person_biography.identity import _clean_name, _identity_from_person_fields
from person_biography.spans import _record_span, _event_date_span, _merge_span
from person_biography.places import _clean_place, place_names_equivalent, _merge_place


_BIRTH_WORDS = {"birth", "geburt"}
_DEATH_WORDS = {
    "death",
    "died",
    "tod",
    "sterben",
    "gestorben",
    "verstorben",
    "murder",
    "mord",
    "ermordung",
    "ermordet",
}
_OTHER_SUBJECT_RE = re.compile(
    r"\b(?:des|der|meines|meiner|seines|seiner|ihres|ihrer|von)\s+"
    r"(?:vaters?|m[uü]tter|eltern|bruders?|schwester|ehemanns?|frau|"
    r"sohnes?|tochter|kindes?|großvaters?|großmutter|onkels?|tante)\b"
    r"|\b(?:vater|mutter|eltern|bruder|schwester|ehemann|frau|sohn|tochter)"
    r"\s+(?:tod|death|mord|murder)\b",
    re.IGNORECASE,
)


def _classify_biographical_event(row: Mapping[str, Any]) -> str | None:
    label = clean_str(row.get("event_label", ""))
    if _OTHER_SUBJECT_RE.search(label):
        return None
    event_type = clean_str(row.get("event_type", ""))
    words = set(re.findall(r"[^\W_]+", f"{event_type} {label}".casefold()))
    if words & _BIRTH_WORDS:
        return "birth"
    if words & _DEATH_WORDS:
        return "death"
    return None


def _metadata_people(record: Mapping[str, Any], aliases: Mapping[str, str]):
    people: dict[str, dict[str, Any]] = {}
    main_person = record.get("person") or {}
    main_key = _identity_from_person_fields(main_person, aliases)
    if main_key:
        people[main_key] = {
            "name": " ".join(
                part
                for part in (
                    _clean_name(main_person.get("given_name")),
                    _clean_name(main_person.get("family_name")),
                )
                if part
            ),
            "birth_span": _record_span(main_person, "birth"),
            "birth_place": _clean_place((record.get("birth_place") or {}).get("name")),
            "death_span": _record_span(main_person, "death"),
            "death_place": None,
        }

    for relative in record.get("family", []):
        key = _identity_from_person_fields(relative, aliases)
        if not key:
            continue
        name = " ".join(
            part
            for part in (
                _clean_name(relative.get("given_name")),
                _clean_name(relative.get("family_name")),
            )
            if part
        )
        candidate: dict[str, Any] = {
            "name": name,
            "birth_span": _record_span(relative, "birth"),
            "birth_place": _clean_place(relative.get("birth_place")),
            "death_span": _record_span(relative, "death"),
            "death_place": None,
        }
        current = people.get(key)
        if current is None:
            people[key] = candidate
            continue
        conflicts = []
        current["birth_span"] = _merge_span(
            current["birth_span"],
            candidate["birth_span"],
            description=f"Metadata birth dates for {name!r}",
            conflicts=conflicts,
        )
        current["death_span"] = _merge_span(
            current["death_span"],
            candidate["death_span"],
            description=f"Metadata death dates for {name!r}",
            conflicts=conflicts,
        )
        current["birth_place"] = _merge_place(
            current["birth_place"],
            candidate["birth_place"],
            description=f"Metadata birth places for {name!r}",
            conflicts=conflicts,
        )
        current["death_place"] = _merge_place(
            current["death_place"],
            candidate["death_place"],
            description=f"Metadata death places for {name!r}",
            conflicts=conflicts,
        )
        if conflicts:
            raise PersonBiographyConflictError(conflicts)
    return people


def _collect_sheet_facts(
    person_name: str,
    identity_key: str,
    rows: list[Mapping[str, Any]],
    source_label: str,
    conflicts: list[str],
) -> _MutableBiography:
    facts = _MutableBiography(person_name=person_name, identity_key=identity_key)
    facts.source_workbooks.add(source_label)
    for row in rows:
        kind = _classify_biographical_event(row)
        if not kind:
            continue
        facts.has_biographical_event = True
        event_label = clean_str(row.get("event_label", "")) or kind
        event_context = (
            f"{person_name!r} {kind} event {event_label!r} in {source_label!r}"
        )
        span = _event_date_span(row)
        place = _clean_place(row.get("place_name"))
        place_detail = _clean_place(row.get("place_detail"))
        if place and place_detail and not place_names_equivalent(place, place_detail):
            place = f"{place} ({place_detail})"
        if kind == "birth":
            facts.birth_span = _merge_span(
                facts.birth_span,
                span,
                description=f"Chronotopi birth dates for {event_context}",
                conflicts=conflicts,
            )
            facts.birth_place = _merge_place(
                facts.birth_place,
                place,
                description=f"Chronotopi birth places for {event_context}",
                conflicts=conflicts,
            )
        else:
            facts.death_span = _merge_span(
                facts.death_span,
                span,
                description=f"Chronotopi death dates for {event_context}",
                conflicts=conflicts,
            )
            facts.death_place = _merge_place(
                facts.death_place,
                place,
                description=f"Chronotopi death places for {event_context}",
                conflicts=conflicts,
            )
    return facts


def _rows_for_sheet(dataframe, workbook_name: str, sheet_name: str):
    if not hasattr(dataframe, "columns"):
        raise PersonBiographyError("Chronotopi events must be supplied as a dataframe")
    selected = dataframe
    if "source_workbook" in selected.columns:
        selected = selected[selected["source_workbook"].map(_basename) == workbook_name]
    if "name" in selected.columns:
        selected = selected[
            selected["name"].map(_clean_name) == _clean_name(sheet_name)
        ]
    return selected.to_dict("records")


def _basename(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _metadata_for_workbook(metadata_path: Path, aliases: Mapping[str, str]):
    from metadati import read_person_record

    return _metadata_people(read_person_record(metadata_path), aliases)
