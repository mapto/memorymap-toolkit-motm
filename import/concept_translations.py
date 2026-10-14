"""Provide shared database and gettext helpers for Concept translation maintenance.

The executable entry points live in ``export_concept_translations.py`` and
``import_concept_translations.py``. Keeping the database access, PO handling,
and legacy-data repair rules here gives both commands the same identity and
validation rules without coupling either command to Django's application
startup. That matters because these scripts are also useful from the host
notebook environment, where the repository ``.env`` file is the configuration
source but Django is not necessarily installed.

The legacy database has Concept labels stored in the ``en`` Parler language
slot even though most labels are German. ``bootstrap_catalogs`` therefore has
an explicit repair mode: it infers the likely source language, keeps the
readable form of that label as the source value, reuses unambiguous entries
from supplied catalogs, and fills the remaining languages through the
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
    before any database rows are changed. The PO parser, catalog checks,
    bootstrap, and translation helpers raise it. The command-line entry
    points do not catch it, so a failure ends the run with a non-zero exit.
    """


def load_dotenv(path: Path) -> dict[str, str]:
    """Read the small ``KEY=value`` subset needed by these standalone scripts.

    A local parser avoids making Django or an additional dotenv package a
    prerequisite for export/import. It handles comments, optional ``export``
    prefixes, and simple quoted values, which covers the repository's
    ``.env`` file. Command-line overrides are applied later by
    ``database_connection``. A missing file yields an empty dict.
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
    """Open a PostgreSQL connection from ``.env`` defaults and CLI overrides.

    The compose stack exposes different host/port pairs from inside and
    outside Docker (the README uses port 5433 from the host), so callers must
    be able to override connection details without editing ``.env``. Empty
    override values are ignored. Missing settings fall back to the
    ``memorymap`` database, the ``memorymapper`` user, and localhost port 5432.
    Direct psycopg2 access lets the utilities read and write the Parler table
    without booting the full web app. The caller owns the returned connection
    and should close it.
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
    complete catalog from the legacy all-``en`` state. Both command-line entry
    points start with this read-only query. The result maps each master ID to
    ``{language_code: label}``, with NULL labels as empty strings. An empty
    table raises ``ConceptTranslationError``.
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
    claim of perfect language detection. Known German and English taxonomy
    codes and labels are matched first, then German characters and stop words,
    then an underscore, which marks an English code. Anything still ambiguous
    defaults to German because the inspected legacy data is predominantly
    German. Returns ``"de"`` or ``"en"``. Only the opt-in bootstrap calls this.
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
    than prose. Mapping them to the readable form gives useful PO source
    strings, while the database concept ID stays the authoritative key. Other
    labels are returned stripped but otherwise unchanged. Only the legacy
    machine-translation path in ``bootstrap_catalogs`` calls this.
    """
    normalized = label.strip()
    lowered = normalized.lower()
    return GERMAN_CODE_LABELS.get(lowered, ENGLISH_CODE_LABELS.get(lowered, normalized))


def _po_value(value: str) -> str:
    """Return ``value`` as one double-quoted PO string literal.

    ``json.dumps`` keeps umlauts and other Unicode readable in the catalog
    while escaping quotes, backslashes, and newlines. The escapes are the ones
    ``_decode_po_value`` reads back with ``ast.literal_eval``, so writing and
    parsing stay symmetric.
    """
    return json.dumps(value, ensure_ascii=False)


def _po_field(name: str, value: str) -> list[str]:
    """Format a PO field, using continuation lines when a value contains newlines.

    A value that contains newlines is written as an empty first string followed
    by one quoted fragment per source line, the layout gettext tools use for
    multi-line strings. That keeps such labels readable and easy to review in
    diffs. Returns the field as a list of lines.
    """
    if "\n" not in value:
        return [f"{name} {_po_value(value)}"]
    lines = [f'{name} ""']
    for line in value.splitlines(keepends=True):
        lines.append(_po_value(line))
    return lines


def _decode_po_value(value: str) -> str:
    """Decode one quoted PO fragment, either after a keyword or on its own line.

    ``ast.literal_eval`` accepts only Python literals, so reading a catalog
    cannot execute code. Raises ``ConceptTranslationError`` when the text is
    not a string literal.
    """
    try:
        decoded = ast.literal_eval(value)
    except (SyntaxError, ValueError) as error:
        raise ConceptTranslationError(f"Invalid PO string: {value}") from error
    if not isinstance(decoded, str):
        raise ConceptTranslationError(f"PO value is not a string: {value}")
    return decoded


def parse_po(path: Path) -> dict[int, dict[str, str]]:
    """Read the concept entries from a generated PO catalog.

    The parser accepts only the small PO shape that ``write_po`` produces, so
    import never has to interpret arbitrary gettext files. Comments, the
    header, and entries without a ``concept:`` context are skipped. An
    unsupported line, a non-integer concept suffix, or a duplicate ID raises
    ``ConceptTranslationError`` so an import cannot target the wrong rows.
    Returns a dict from concept ID to ``msgid`` and ``msgstr``.
    """
    entries: dict[int, dict[str, str]] = {}
    current: dict[str, str] = {}
    active_field: str | None = None

    def flush() -> None:
        """Store the entry collected so far under its concept ID, then reset it.

        Blank lines and end of file close an entry. Entries without a
        ``concept:`` context are dropped, and bad or repeated IDs raise
        ``ConceptTranslationError``.
        """
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
    """Build deterministic gettext metadata for one supported language.

    gettext tools expect a header that declares the charset and plural rules,
    so every catalog carries one. The timestamps are fixed rather than read
    from the clock, which keeps repeated exports identical when the database
    has not changed. ``parse_po`` skips this entry because it has no
    ``concept:`` context. Returns the header as PO lines.
    """
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
    """Write an ID-stable PO catalog for one language.

    Entries are sorted by Concept ID to keep diffs reviewable and to make
    repeated exports deterministic. The parent directory is created here so a
    fresh checkout or a custom output root works. Any existing file is
    overwritten, as UTF-8. The function does not check completeness;
    ``bootstrap_catalogs`` does that before export calls it.
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

    Only the explicit ``--machine-translate`` repair reaches this function, so
    ordinary import and export stay offline and deterministic. Text is returned
    unchanged when the languages match or the text is empty. Otherwise the
    function sends a GET request to the MyMemory API and sleeps for ``delay``
    seconds after each success. Failures are retried with exponential backoff,
    up to four attempts in total. After the last attempt it raises
    ``ConceptTranslationError``, so a partial translation is never returned.
    """
    if source == target or not text:
        return text
    query = urllib.parse.urlencode({"q": text, "langpair": f"{source}|{target}"})
    url = f"https://api.mymemory.translated.net/get?{query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "memorymap-toolkit/1.0"}
    )
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
        except (
            ConceptTranslationError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)

    raise ConceptTranslationError(
        f"Translation request failed for {source}->{target}: {text}"
    ) from last_error


def reusable_translation_values(
    existing_catalogs: dict[str, dict[int, dict[str, str]]] | None,
    source_label: str,
    source_language: str,
) -> dict[str, str] | None:
    """Reuse one unambiguous complete entry from an older PO catalog set.

    When ``bootstrap_catalogs`` runs with existing catalogs, a legacy label that
    already has reviewed text keeps that wording instead of going to the
    translation service. The source label is compared case-insensitively with
    the source-language ``msgstr``. Only concepts with non-empty en, de, and it
    entries and one shared msgid count as candidates. If the candidates disagree
    or there are none, this returns None so the caller translates instead of
    guessing. The function has no side effects.
    """
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
        complete_entries = {
            language: entry
            for language, entry in entries.items()
            if entry and entry.get("msgstr", "").strip()
        }
        if len(complete_entries) != len(entries):
            continue
        if len({entry.get("msgid", "") for entry in complete_entries.values()}) != 1:
            continue
        candidates.append(
            tuple(entry["msgstr"].strip() for entry in complete_entries.values())
        )

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

    Without machine translation this is a strict completeness check, and a
    concept missing any language raises ``ConceptTranslationError``. With it
    enabled, legacy all-``en`` rows are reinterpreted with
    ``infer_source_language`` and existing values are kept. Legacy rows first
    try unambiguous entries in ``existing_catalogs``, and any language still
    missing is filled through ``translate_text``. A per-run cache sends each
    request once. The catalogs still need human review before import.

    Args:
        concepts: Rows from ``fetch_concepts``, keyed by concept ID.
        use_machine_translation: Enable the legacy repair path.
        delay: Seconds to pause after each successful translation request.
        existing_catalogs: Previously written catalogs to reuse, or None.

    Returns:
        ``{language: {concept_id: {"msgid": ..., "msgstr": ...}}}``, where
        ``msgid`` is always the English label.
    """
    catalogs = {language: {} for language in LANGUAGES}
    cache: dict[tuple[str, str, str], str] = {}

    def translated(text: str, source: str, target: str) -> str:
        """Reuse identical translation requests within this export run.

        Concept labels are not unique, so the same text can recur across rows.
        The cache lives for one ``bootstrap_catalogs`` call, so each
        (text, source, target) request reaches ``translate_text`` at most once.
        """
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
                        values[target] = translated(
                            source_label, source_language, target
                        )
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
                        values[target] = translated(
                            source_label, source_language, target
                        )

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

    Both command-line entry points pass their parsed options here. The
    ``--dotenv``, ``--host``, ``--port``, ``--database``, ``--user``, and
    ``--password`` options map onto ``database_connection``, and a missing
    ``--dotenv`` selects the repository ``.env`` file. Keeping this mapping in
    the shared module gives both commands the same fallback and override rules.
    Returns the open psycopg2 connection.
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
