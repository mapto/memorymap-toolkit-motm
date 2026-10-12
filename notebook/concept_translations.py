"""Shared database and gettext helpers for Concept translation maintenance.

The executable entry points live in ``export_concept_translations.py`` and
``import_concept_translations.py``. Keeping the database access, PO handling,
and legacy-data repair rules here gives both commands the same identity and
validation rules without coupling either command to Django's application
startup. That matters because these scripts are also useful from the host
notebook environment, where the repository ``.env`` file is the configuration
source but Django is not necessarily installed.

The legacy database has Concept labels stored in the ``en`` Parler language
slot even though most labels are German. ``bootstrap_catalogs`` therefore has
an explicit repair mode: it infers the likely source language, preserves that
label as the source value, and fills the other two languages through the
translation service. Ordinary export remains strict so a later missing
translation cannot silently become a new machine-generated value. The PO
files use the English label as the stable ``msgid`` and ``concept:<id>`` as
``msgctxt``; the context is what lets import map a translated string back to
the correct database row even when labels are duplicated or edited.
"""

from __future__ import annotations

import ast
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2


LANGUAGES = ("en", "de", "it")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOTENV = ROOT / ".env"
DEFAULT_LOCALE_ROOT = ROOT / "locale"
TRANSLATION_TABLE = "mmt_motm_concept_translation"

GERMAN_CODE_LABELS = {
    "alte_heimat": "Alte Heimat",
    "erinnerungsort": "Erinnerungsort",
    "neue_heimat": "Neue Heimat",
    "ort_der_zeit": "Ort der Zeit",
    "reise_zurueck": "Reise zurück",
}

ENGLISH_CODE_LABELS = {
    "arrest": "Arrest",
    "birth": "Birth",
    "death": "Death",
    "deportation": "Deportation",
    "education": "Education",
    "emigration_transit": "Emigration transit",
    "farewell": "Farewell",
    "forced_designation": "Forced designation",
    "forced_eviction": "Forced eviction",
    "immigration": "Immigration",
    "marriage": "Marriage",
    "memorial_gedenkbuch_berlin": "Memorial Gedenkbuch Berlin",
    "memorial_gedenkbuch_bundesarchiv": "Memorial Gedenkbuch Bundesarchiv",
    "memorial_stolperstein": "Memorial Stolperstein",
    "memorial_street_name": "Memorial street name",
    "memorial_yad_vashem": "Memorial Yad Vashem",
    "military_service": "Military service",
    "murder": "Murder",
    "notification": "Notification",
    "residence": "Residence",
    "residence_change": "Residence change",
    "return_visit": "Return visit",
    "return_visit_transit": "Return visit transit",
    "train": "Train",
    "transport_arrival": "Transport arrival",
    "transport_departure": "Transport departure",
    "work": "Work",
}

ENGLISH_LABELS = {
    "English",
    "Jewish Agency",
    "code-switching",
    "code switching",
    "administrative",
}

GERMAN_WORDS = {
    "alte",
    "als",
    "auf",
    "aus",
    "bei",
    "der",
    "die",
    "ein",
    "eine",
    "eltern",
    "für",
    "im",
    "in",
    "jüdische",
    "mit",
    "nach",
    "neue",
    "und",
    "von",
    "zu",
}


class ConceptTranslationError(RuntimeError):
    """Signal a fail-closed catalog or database condition.

    Translation data is shared application state, so malformed PO syntax,
    incomplete catalogs, and unknown concept IDs should stop the operation
    before any database rows are changed.
    """


def load_dotenv(path: Path) -> dict[str, str]:
    """Read the small ``KEY=value`` subset needed by these standalone scripts.

    A local parser avoids making Django or an additional dotenv package a
    prerequisite for export/import. It intentionally handles comments,
    optional ``export`` prefixes, and simple quoted values, which covers the
    repository's `.env` file; command-line overrides are applied later.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def database_connection(dotenv_path: Path, overrides: dict[str, str] | None = None):
    """Open PostgreSQL using `.env` defaults with explicit CLI overrides.

    The compose stack exposes different host/port pairs from inside and
    outside Docker, so the scripts must allow callers to override connection
    details without editing `.env`. Direct psycopg2 access also lets the
    utility operate on the Parler table without booting the full web app.
    """
    values = load_dotenv(dotenv_path)
    values.update({key: value for key, value in (overrides or {}).items() if value})
    return psycopg2.connect(
        dbname=values.get("DJANGO_DB_NAME", "memorymap"),
        user=values.get("DJANGO_DB_USER", "memorymapper"),
        password=values.get("DJANGO_DB_PASSWORD", ""),
        host=values.get("DJANGO_DB_HOST", "localhost"),
        port=values.get("DJANGO_DB_PORT", "5432"),
    )


def fetch_concepts(connection) -> dict[int, dict[str, str]]:
    """Return every Concept label grouped by database ID and language.

    The master ID is retained as the primary identity because labels are not
    unique and the old data has incorrect language codes. Reading all rows in
    one shape gives export and bootstrap the evidence needed to distinguish a
    complete catalog from the legacy all-``en`` state.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT master_id, language_code, label
            FROM {TRANSLATION_TABLE}
            ORDER BY master_id, language_code
            """
        )
        concepts: dict[int, dict[str, str]] = {}
        for master_id, language_code, label in cursor.fetchall():
            concepts.setdefault(master_id, {})[language_code] = (label or "").strip()
    if not concepts:
        raise ConceptTranslationError("No concept translations were found.")
    return concepts


def infer_source_language(label: str) -> str:
    """Choose the likely source language for a legacy label.

    This is deliberately a conservative, explainable heuristic rather than a
    claim of perfect language detection: taxonomy codes and known English
    labels are handled explicitly, German markers are recognized next, and
    ambiguous labels default to German because the inspected legacy data is
    predominantly German. The result is used only by the opt-in bootstrap.
    """
    normalized = label.strip()
    lowered = normalized.lower()
    if lowered in GERMAN_CODE_LABELS:
        return "de"
    if lowered in ENGLISH_CODE_LABELS or normalized in ENGLISH_LABELS:
        return "en"
    if any(character in normalized for character in "äöüÄÖÜß"):
        return "de"
    words = set(re.findall(r"[a-zA-ZäöüÄÖÜß]+", lowered))
    if words & GERMAN_WORDS:
        return "de"
    if "_" in normalized:
        return "en"
    return "de"


def canonical_source_label(label: str) -> str:
    """Normalize machine taxonomy codes into readable source labels.

    A few imported concepts are identifiers such as ``alte_heimat`` rather
    than prose. Translating the human-readable form produces useful PO source
    strings while retaining the database concept ID as the authoritative key.
    """
    normalized = label.strip()
    lowered = normalized.lower()
    return GERMAN_CODE_LABELS.get(lowered, ENGLISH_CODE_LABELS.get(lowered, normalized))


def _po_value(value: str) -> str:
    """Encode one PO string with Unicode preserved and escapes quoted safely."""
    return json.dumps(value, ensure_ascii=False)


def _po_field(name: str, value: str) -> list[str]:
    """Format a PO field, using continuation lines when a value contains newlines.

    Keeping multiline formatting valid is important for the long concept
    labels in this dataset; a single-line shortcut would produce catalogs that
    gettext tools cannot parse reliably.
    """
    if "\n" not in value:
        return [f"{name} {_po_value(value)}"]
    lines = [f'{name} ""']
    for line in value.splitlines(keepends=True):
        lines.append(_po_value(line))
    return lines


def _decode_po_value(value: str) -> str:
    """Decode one quoted PO fragment without evaluating arbitrary code."""
    try:
        decoded = ast.literal_eval(value)
    except (SyntaxError, ValueError) as error:
        raise ConceptTranslationError(f"Invalid PO string: {value}") from error
    if not isinstance(decoded, str):
        raise ConceptTranslationError(f"PO value is not a string: {value}")
    return decoded


def parse_po(path: Path) -> dict[int, dict[str, str]]:
    """Read the concept entries from a generated PO catalog.

    The parser accepts the deliberately small PO shape written by
    ``write_po``. Header entries and comments are ignored, while malformed
    syntax, invalid concept contexts, and duplicate IDs fail loudly so an
    import cannot accidentally target the wrong rows.
    """
    entries: dict[int, dict[str, str]] = {}
    current: dict[str, str] = {}
    active_field: str | None = None

    def flush() -> None:
        nonlocal current
        context = current.get("msgctxt", "")
        if context.startswith("concept:"):
            try:
                concept_id = int(context.removeprefix("concept:"))
            except ValueError as error:
                raise ConceptTranslationError(
                    f"Invalid concept context in {path}: {context}"
                ) from error
            if concept_id in entries:
                raise ConceptTranslationError(
                    f"Duplicate concept {concept_id} in {path}"
                )
            entries[concept_id] = {
                "msgid": current.get("msgid", ""),
                "msgstr": current.get("msgstr", ""),
            }
        current = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            active_field = None
            continue
        if line.startswith("#"):
            continue
        matched = re.match(r"(msgctxt|msgid|msgstr) (.+)$", line)
        if matched:
            active_field = matched.group(1)
            current[active_field] = _decode_po_value(matched.group(2))
            continue
        if line.startswith('"') and active_field:
            current[active_field] += _decode_po_value(line)
            continue
        raise ConceptTranslationError(f"Unsupported PO line in {path}: {raw_line}")
    flush()
    return entries


def _catalog_header(language: str) -> list[str]:
    """Build deterministic gettext metadata for one supported language."""
    language_names = {"en": "English", "de": "German", "it": "Italian"}
    plural_forms = {
        "en": "nplurals=2; plural=(n != 1);",
        "de": "nplurals=2; plural=(n != 1);",
        "it": "nplurals=2; plural=(n != 1);",
    }
    metadata = [
        "Project-Id-Version: memorymap-toolkit-concepts\n",
        "Report-Msgid-Bugs-To: \n",
        "POT-Creation-Date: 2026-10-07 00:00+0000\n",
        "PO-Revision-Date: 2026-10-07 00:00+0000\n",
        "Last-Translator: \n",
        "Language-Team: " + language_names[language] + "\n",
        "Language: " + language + "\n",
        "MIME-Version: 1.0\n",
        "Content-Type: text/plain; charset=UTF-8\n",
        "Content-Transfer-Encoding: 8bit\n",
        "Plural-Forms: " + plural_forms[language] + "\n",
    ]
    lines = ['msgid ""', 'msgstr ""']
    lines.extend(_po_value(value) for value in metadata)
    return lines


def write_po(path: Path, language: str, entries: dict[int, dict[str, str]]) -> None:
    """Write a complete, ID-stable PO catalog for one language.

    Entries are sorted by Concept ID to keep diffs reviewable and to make
    repeated exports deterministic. The parent directory is created here so
    the command works with a fresh checkout or a custom output root.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _catalog_header(language)
    for concept_id in sorted(entries):
        entry = entries[concept_id]
        lines.extend(
            [
                "",
                f'msgctxt "concept:{concept_id}"',
                *_po_field("msgid", entry["msgid"]),
                *_po_field("msgstr", entry["msgstr"]),
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def translate_text(text: str, source: str, target: str, delay: float = 0.15) -> str:
    """Translate one label through the public service used only for bootstrap.

    Normal import/export is offline and deterministic. Isolating this network
    call behind one function makes the opt-in repair boundary explicit and
    lets the caller control request pacing; failures become a domain error
    instead of producing a partial translation.
    """
    if source == target or not text:
        return text
    query = urllib.parse.urlencode(
        {"q": text, "langpair": f"{source}|{target}"}
    )
    url = f"https://api.mymemory.translated.net/get?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "memorymap-toolkit/1.0"})
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if payload.get("responseStatus") != 200:
                raise ConceptTranslationError(
                    f"Translation service rejected {source}->{target}: "
                    f"{payload.get('responseDetails', 'unknown error')}"
                )
            translated = html.unescape(
                payload.get("responseData", {}).get("translatedText", "")
            ).strip()
            if not translated or translated.upper().startswith("MYMEMORY WARNING"):
                raise ConceptTranslationError(f"Empty translation returned for: {text}")
            time.sleep(delay)
            return translated
        except (ConceptTranslationError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 3:
                time.sleep(2 ** attempt)

    raise ConceptTranslationError(
        f"Translation request failed for {source}->{target}: {text}"
    ) from last_error


def reusable_translation_values(
    existing_catalogs: dict[str, dict[int, dict[str, str]]] | None,
    source_label: str,
    source_language: str,
) -> dict[str, str] | None:
    """Reuse one unambiguous complete entry from an older PO catalog set."""
    if not existing_catalogs:
        return None

    candidates = []
    source_entries = existing_catalogs.get(source_language, {})
    for concept_id, source_entry in source_entries.items():
        if source_entry.get("msgstr", "").strip().casefold() != source_label.casefold():
            continue
        entries = {
            language: existing_catalogs.get(language, {}).get(concept_id)
            for language in LANGUAGES
        }
        if any(not entry or not entry.get("msgstr", "").strip() for entry in entries.values()):
            continue
        if len({entry.get("msgid", "") for entry in entries.values()}) != 1:
            continue
        candidates.append(tuple(entry["msgstr"].strip() for entry in entries.values()))

    distinct_candidates = set(candidates)
    if len(distinct_candidates) != 1:
        return None
    return dict(zip(LANGUAGES, distinct_candidates.pop()))


def bootstrap_catalogs(
    concepts: dict[int, dict[str, str]],
    use_machine_translation: bool,
    delay: float,
    existing_catalogs: dict[str, dict[int, dict[str, str]]] | None = None,
) -> dict[str, dict[int, dict[str, str]]]:
    """Build complete English, German, and Italian catalogs from DB rows.

    Without machine translation this function is a strict completeness check.
    With it enabled, the legacy all-``en`` rows are reinterpreted using the
    source-language heuristic, existing values are preserved, and only missing
    target languages are translated. A small in-run cache avoids sending the
    same label to the public service more than once; the resulting catalogs
    still require human review before import.
    """
    catalogs = {language: {} for language in LANGUAGES}
    cache: dict[tuple[str, str, str], str] = {}

    def translated(text: str, source: str, target: str) -> str:
        """Reuse identical translation requests within this export run."""
        key = (text, source, target)
        if key not in cache:
            cache[key] = translate_text(text, source, target, delay)
        return cache[key]

    for concept_id, existing in sorted(concepts.items()):
        if use_machine_translation and set(existing) == {"en"}:
            source_label = canonical_source_label(existing["en"])
            source_language = infer_source_language(existing["en"])
            values = reusable_translation_values(
                existing_catalogs,
                source_label,
                source_language,
            )
            if values is None:
                values = {source_language: source_label}
                for target in LANGUAGES:
                    if target not in values:
                        values[target] = translated(source_label, source_language, target)
        else:
            values = {language: existing.get(language, "") for language in LANGUAGES}
            if use_machine_translation:
                source_language = "de" if values.get("de") else "en"
                source_label = values.get(source_language, "")
                if not source_label:
                    raise ConceptTranslationError(
                        f"Concept {concept_id} has no source label to translate."
                    )
                for target in LANGUAGES:
                    if not values.get(target):
                        values[target] = translated(source_label, source_language, target)

        if not all(values.get(language) for language in LANGUAGES):
            missing = [language for language in LANGUAGES if not values.get(language)]
            raise ConceptTranslationError(
                f"Concept {concept_id} is missing translations: {', '.join(missing)}"
            )
        english_label = values["en"]
        for language in LANGUAGES:
            catalogs[language][concept_id] = {
                "msgid": english_label,
                "msgstr": values[language],
            }
    return catalogs


def connection_from_arguments(args):
    """Adapt docpie's option mapping to the shared DB connection helper.

    Keeping this adapter in the shared module ensures both entry points use
    identical `.env` fallback and Docker host/port override behavior while
    leaving their command-specific orchestration independent.
    """
    dotenv_value = args.get("--dotenv")
    overrides = {
        "DJANGO_DB_HOST": args.get("--host"),
        "DJANGO_DB_PORT": args.get("--port"),
        "DJANGO_DB_NAME": args.get("--database"),
        "DJANGO_DB_USER": args.get("--user"),
        "DJANGO_DB_PASSWORD": args.get("--password"),
    }
    dotenv_path = Path(dotenv_value) if dotenv_value else DEFAULT_DOTENV
    return database_connection(dotenv_path, overrides)