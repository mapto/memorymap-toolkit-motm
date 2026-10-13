"""Extract, validate, and import birth/death facts from chronotopi sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping

from api_client import api_get, api_patch, get_or_create_timespan, get_person_id
from locations import get_or_create_location, taxonomy_alias
from person_taxonomy import load_person_taxonomy_synonyms, person_taxonomy_key
from timespan import Timespan, parse_timespan
from utils import clean_str


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


def _clean_name(value: Any) -> str:
    return " ".join(clean_str(value).split()).strip(" ,")


def _alias_target(name: str, aliases: Mapping[str, str]) -> str | None:
    key = person_taxonomy_key(name)
    target = aliases.get(key)
    if target:
        return target
    for canonical in aliases.values():
        if key == person_taxonomy_key(canonical):
            return canonical
        if "," in canonical:
            family_name, given_name = (part.strip() for part in canonical.split(",", 1))
            if key == person_taxonomy_key(f"{given_name} {family_name}"):
                return canonical
    return None


def _identity_from_name(name: str, aliases: Mapping[str, str]) -> str:
    cleaned = _clean_name(name)
    target = _alias_target(cleaned, aliases)
    return person_taxonomy_key(target or cleaned)


def _identity_from_person_fields(
    person: Mapping[str, Any], aliases: Mapping[str, str]
) -> str | None:
    given_names = [
        _clean_name(person.get("given_name")),
        _clean_name(person.get("previous_given_name")),
    ]
    family_names = [
        _clean_name(person.get("family_name")),
        _clean_name(person.get("previous_family_name")),
    ]
    for given_name in dict.fromkeys(name for name in given_names if name):
        for family_name in dict.fromkeys(name for name in family_names if name):
            for variant in (
                f"{given_name} {family_name}",
                f"{family_name}, {given_name}",
            ):
                target = _alias_target(variant, aliases)
                if target:
                    return person_taxonomy_key(target)
    given_name = next((name for name in given_names if name), "")
    family_name = next((name for name in family_names if name), "")
    fallback = " ".join(part for part in (given_name, family_name) if part)
    return person_taxonomy_key(fallback) if fallback else None


def _parse_span(value: Any) -> Timespan | None:
    text = clean_str(value)
    if not text:
        return None
    try:
        parsed = parse_timespan(text)
    except (OverflowError, ValueError):
        return None
    if parsed.start is None:
        return None
    return Timespan(
        parsed.start,
        parsed.end or parsed.start,
        is_point=parsed.start == (parsed.end or parsed.start),
        certainty=parsed.certainty,
    )


def _span_from_interval(value: Any) -> Timespan | None:
    if isinstance(value, Timespan):
        return value if value.start else None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    start_span = _parse_span(value[0])
    end_span = _parse_span(value[1])
    if start_span is None or end_span is None:
        return None
    start = start_span.start
    end = end_span.end or end_span.start
    if start is None or end is None or start > end:
        return None
    return Timespan(start, end, is_point=start == end)


def _record_span(record: Mapping[str, Any], field_name: str) -> Timespan | None:
    interval = _span_from_interval(record.get(f"{field_name}_date_interval"))
    return interval or _parse_span(record.get(f"{field_name}_date"))


def _span_intersection(left: Timespan, right: Timespan) -> Timespan | None:
    if left.start is None or right.start is None:
        return None
    left_end = left.end or left.start
    right_end = right.end or right.start
    start = max(left.start, right.start)
    end = min(left_end, right_end)
    if start > end:
        return None
    return Timespan(start, end, is_point=start == end)


def _span_label(span: Timespan | None) -> str:
    if span is None or span.start is None:
        return "unknown"
    end = span.end or span.start
    if span.start == end:
        return span.start.isoformat()
    return f"{span.start.isoformat()} through {end.isoformat()}"


def _clean_place(value: Any) -> str | None:
    text = clean_str(value)
    place = text.splitlines()[0].strip() if text else ""
    if not place or place.casefold() in {"?", "-", "n/a", "unknown"}:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", place):
        return None
    return place


def _normalized_place(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("ß", "ss"))
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(sorted(re.findall(r"[^\W_]+", unaccented, flags=re.UNICODE)))


def _place_match_keys(value: Any) -> set[str]:
    place = _clean_place(value)
    if not place:
        return set()
    candidates = [place]
    visited = set()
    keys = set()
    while candidates:
        candidate = candidates.pop()
        if candidate in visited:
            continue
        visited.add(candidate)
        alias = taxonomy_alias(candidate)
        if alias and alias != candidate:
            candidates.append(alias)
        without_parenthetical = re.sub(r"\s*\([^()]*\)", "", candidate).strip()
        if without_parenthetical != candidate:
            candidates.append(without_parenthetical)
        candidates.extend(
            part.strip() for part in re.split(r"\s*/\s*", candidate) if part.strip()
        )
        normalized = _normalized_place(candidate)
        if normalized:
            keys.add(normalized)
    return keys


def place_names_equivalent(left: Any, right: Any) -> bool:
    """Compare place spellings conservatively, allowing reviewed aliases/details."""
    left_keys = _place_match_keys(left)
    return bool(left_keys and left_keys.intersection(_place_match_keys(right)))


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


def _event_date_span(row: Mapping[str, Any]) -> Timespan | None:
    start_raw = clean_str(row.get("date_start", ""))
    end_raw = clean_str(row.get("date_end", ""))
    label_span = _parse_span(row.get("date_label", ""))
    start_span = _parse_span(start_raw) if start_raw else None
    end_span = _parse_span(end_raw) if end_raw else None

    if (start_raw and start_span is None) or (end_raw and end_span is None):
        return label_span
    if start_span or end_span:
        start = (start_span or end_span).start
        end_source = end_span or start_span
        end = end_source.end or end_source.start
        if start and end and start <= end:
            # Some sheets prefill year-only dates as Jan 1 in both event date
            # columns while retaining the year-only precision in date_label.
            # Recover that precision rather than treating the sentinel as exact.
            if (
                label_span
                and label_span.start
                and label_span.end
                and label_span.start < label_span.end
                and start == end
                and start in {label_span.start, label_span.end}
            ):
                return label_span
            return Timespan(start, end, is_point=start == end)
    return label_span


def _merge_span(
    existing: Timespan | None,
    incoming: Timespan | None,
    *,
    description: str,
    conflicts: list[str],
) -> Timespan | None:
    if existing is None:
        return incoming
    if incoming is None:
        return existing
    intersection = _span_intersection(existing, incoming)
    if intersection is None:
        conflicts.append(
            f"{description}: {_span_label(existing)} conflicts with "
            f"{_span_label(incoming)}"
        )
        return existing
    return intersection


def _merge_place(
    existing: str | None,
    incoming: str | None,
    *,
    description: str,
    conflicts: list[str],
) -> str | None:
    if existing and incoming and not place_names_equivalent(existing, incoming):
        conflicts.append(f"{description}: {existing!r} conflicts with {incoming!r}")
        return existing
    return existing or incoming


def _metadata_people(record: Mapping[str, Any], aliases: Mapping[str, str]):
    people = {}
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
        candidate = {
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


def _combine_source_facts(
    event_facts: _MutableBiography,
    metadata: Mapping[str, Any] | None,
    metadata_name: str,
    conflicts: list[str],
) -> _MutableBiography:
    if metadata is None:
        return event_facts

    metadata_context = f"metadata workbook {metadata_name!r}"
    for kind in ("birth", "death"):
        event_span = getattr(event_facts, f"{kind}_span")
        metadata_span = metadata.get(f"{kind}_span")
        if event_span and metadata_span:
            intersection = _span_intersection(event_span, metadata_span)
            if intersection is None:
                conflicts.append(
                    f"{event_facts.person_name!r} {kind} date: chronotopi "
                    f"{_span_label(event_span)} conflicts with "
                    f"{_span_label(metadata_span)} in {metadata_context}"
                )
            else:
                setattr(event_facts, f"{kind}_span", intersection)
        elif metadata_span:
            setattr(event_facts, f"{kind}_span", metadata_span)

        event_place = getattr(event_facts, f"{kind}_place")
        metadata_place = metadata.get(f"{kind}_place")
        if (
            event_place
            and metadata_place
            and not place_names_equivalent(event_place, metadata_place)
        ):
            conflicts.append(
                f"{event_facts.person_name!r} {kind} place: chronotopi "
                f"{event_place!r} conflicts with {metadata_place!r} in "
                f"{metadata_context}"
            )
        elif metadata_place and not event_place:
            setattr(event_facts, f"{kind}_place", metadata_place)

        setattr(event_facts, f"metadata_{kind}_span", metadata_span)
        setattr(event_facts, f"metadata_{kind}_place", metadata_place)
    return event_facts


def _merge_biographies(
    existing: _MutableBiography,
    incoming: _MutableBiography,
    conflicts: list[str],
) -> None:
    for kind in ("birth", "death"):
        for suffix in ("span", "place"):
            attribute = f"{kind}_{suffix}"
            if suffix == "span":
                merged = _merge_span(
                    getattr(existing, attribute),
                    getattr(incoming, attribute),
                    description=(
                        f"{existing.person_name!r} {kind} facts across "
                        f"{', '.join(sorted(existing.source_workbooks | incoming.source_workbooks))}"
                    ),
                    conflicts=conflicts,
                )
            else:
                merged = _merge_place(
                    getattr(existing, attribute),
                    getattr(incoming, attribute),
                    description=f"{existing.person_name!r} {kind} places across sources",
                    conflicts=conflicts,
                )
            setattr(existing, attribute, merged)

            metadata_attribute = f"metadata_{attribute}"
            if suffix == "span":
                metadata_value = _merge_span(
                    getattr(existing, metadata_attribute),
                    getattr(incoming, metadata_attribute),
                    description=f"Metadata {kind} dates for {existing.person_name!r}",
                    conflicts=conflicts,
                )
            else:
                metadata_value = _merge_place(
                    getattr(existing, metadata_attribute),
                    getattr(incoming, metadata_attribute),
                    description=f"Metadata {kind} places for {existing.person_name!r}",
                    conflicts=conflicts,
                )
            setattr(existing, metadata_attribute, metadata_value)
    existing.source_workbooks.update(incoming.source_workbooks)


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


def _api_identity(person: Mapping[str, Any], aliases: Mapping[str, str]):
    return _identity_from_person_fields(person, aliases)


def _stored_date_span(
    value: Any,
    metadata_span: Timespan | None,
) -> Timespan | None:
    stored = _parse_span(value)
    if stored is None:
        return None
    if metadata_span and metadata_span.start == stored.start:
        return metadata_span
    return Timespan(stored.start, stored.start, is_point=True)


def _location_name(location_id: Any, cache: dict[str, str | None]) -> str | None:
    key = str(location_id)
    if key not in cache:
        location = api_get(f"locations/{location_id}")
        cache[key] = (
            _clean_place(location.get("current_name") or location.get("name"))
            if isinstance(location, Mapping)
            else None
        )
    return cache[key]


def _people_by_identity(people, aliases):
    result: dict[str, list[Mapping[str, Any]]] = {}
    for person in people:
        identity = _api_identity(person, aliases)
        if identity:
            result.setdefault(identity, []).append(person)
    return result


def _as_object_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return [value]
    return []


def validate_existing_person_biographies(plan) -> None:
    """Read-only API preflight for existing Person biography conflicts."""
    biographies = _plan_values(plan)
    if not biographies:
        return
    aliases = load_person_taxonomy_synonyms().aliases
    people = _as_object_list(api_get("persons"))
    people_by_identity = _people_by_identity(people, aliases)
    timespans = {
        str(item.get("id")): item
        for item in _as_object_list(api_get("timespans"))
        if item.get("id") is not None
    }
    location_cache: dict[str, str | None] = {}
    conflicts = []

    for biography in biographies:
        matches = people_by_identity.get(biography.identity_key, [])
        for person in matches:
            timespan_id = person.get("lifespan")
            if timespan_id:
                timespan = timespans.get(str(timespan_id))
                if timespan is None:
                    timespan = api_get(f"timespans/{timespan_id}")
                if isinstance(timespan, Mapping):
                    for kind in ("birth", "death"):
                        incoming = getattr(biography, f"{kind}_span")
                        existing_value = timespan.get(
                            "start" if kind == "birth" else "end"
                        )
                        metadata_span = getattr(biography, f"metadata_{kind}_span")
                        existing_span = _stored_date_span(
                            existing_value,
                            metadata_span,
                        )
                        if (
                            incoming
                            and existing_span
                            and _span_intersection(incoming, existing_span) is None
                        ):
                            conflicts.append(
                                f"Existing Person {person['id']} {kind} date "
                                f"{_span_label(existing_span)} conflicts with "
                                f"planned value {_span_label(incoming)} for "
                                f"{biography.person_name!r}"
                            )

            for kind in ("birth", "death"):
                incoming_place = getattr(biography, f"{kind}_place")
                existing_id = person.get(f"{kind}_place")
                if not incoming_place or not existing_id:
                    continue
                existing_place = _location_name(existing_id, location_cache)
                if existing_place and not place_names_equivalent(
                    incoming_place, existing_place
                ):
                    conflicts.append(
                        f"Existing Person {person['id']} {kind} place "
                        f"{existing_place!r} conflicts with planned value "
                        f"{incoming_place!r} for {biography.person_name!r}"
                    )

    if conflicts:
        raise PersonBiographyConflictError(conflicts)


def _choose_date(
    current_value: Any,
    incoming_span: Timespan | None,
    metadata_span: Timespan | None,
    *,
    person_name: str,
    kind: str,
) -> str | None:
    current = clean_str(current_value) or None
    if incoming_span is None or incoming_span.start is None:
        return current
    incoming_value = incoming_span.start.isoformat()
    if not current:
        return incoming_value
    if current == incoming_value:
        return current

    existing_span = _stored_date_span(current, metadata_span)
    if existing_span and _span_intersection(existing_span, incoming_span):
        if (
            metadata_span
            and metadata_span.start
            and metadata_span.end
            and current == metadata_span.start.isoformat()
            and (
                incoming_span.start > metadata_span.start
                or incoming_span.end < metadata_span.end
            )
        ):
            return incoming_value
        return current

    raise PersonBiographyConflictError(
        [
            f"Existing Person {kind} date {current!r} conflicts with planned "
            f"value {_span_label(incoming_span)} for {person_name!r}"
        ]
    )


def import_person_biographies(
    plan,
    *,
    locations_db=None,
    location_concept_resolver=None,
) -> list[int]:
    """Create/update Person biography fields from a validated source plan."""
    imported = []
    location_cache: dict[str, str | None] = {}
    for biography in _plan_values(plan):
        person_id = get_person_id(biography.person_name, biography.person_name)
        if not person_id:
            continue
        person = api_get(f"persons/{person_id}")
        if not isinstance(person, Mapping):
            raise PersonBiographyError(
                f"Could not refresh Person {person_id} for {biography.person_name!r}"
            )

        current_timespan = {}
        timespan_id = person.get("lifespan")
        if timespan_id:
            result = api_get(f"timespans/{timespan_id}")
            if isinstance(result, Mapping):
                current_timespan = result

        birth_value = _choose_date(
            current_timespan.get("start"),
            biography.birth_span,
            biography.metadata_birth_span,
            person_name=biography.person_name,
            kind="birth",
        )
        death_value = _choose_date(
            current_timespan.get("end"),
            biography.death_span,
            biography.metadata_death_span,
            person_name=biography.person_name,
            kind="death",
        )
        patch = {}
        if birth_value or death_value:
            if birth_value != clean_str(
                current_timespan.get("start")
            ) or death_value != clean_str(current_timespan.get("end")):
                new_timespan_id = get_or_create_timespan(
                    start=birth_value,
                    end=death_value,
                )
                if new_timespan_id and new_timespan_id != timespan_id:
                    patch["lifespan"] = new_timespan_id

        for kind in ("birth", "death"):
            place = getattr(biography, f"{kind}_place")
            if not place:
                continue
            field_name = f"{kind}_place"
            current_id = person.get(field_name)
            if current_id:
                current_name = _location_name(current_id, location_cache)
                if current_name and not place_names_equivalent(place, current_name):
                    raise PersonBiographyConflictError(
                        [
                            f"Existing Person {kind} place {current_name!r} "
                            f"conflicts with planned value {place!r} for "
                            f"{biography.person_name!r}"
                        ]
                    )
                continue

            concept_id = (
                location_concept_resolver(place) if location_concept_resolver else None
            )
            location_id = get_or_create_location(
                place,
                locations_db=locations_db,
                concept_id=concept_id,
            )
            if location_id:
                patch[field_name] = location_id

        if patch:
            api_patch("persons", person_id, patch)
        imported.append(person_id)
    return imported
