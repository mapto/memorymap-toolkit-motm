#!/usr/bin/env python3
"""Import locale/*/LC_MESSAGES/concepts.po into the Concept translation table.

This is the validated PO-to-database half of the round trip. It keeps the
shared parser and database helpers in ``concept_translations.py`` while owning
the import-only rules: every database Concept must occur in all three catalogs,
the English ``msgid`` must agree across them, and every ``msgstr`` must be
non-empty. Those checks happen before the transaction writes anything because
an incomplete localization set is more dangerous than a failed import. Only
after they pass does the command upsert one row per concept and language, all
in one transaction. ``--dry-run`` stops after the checks.

Example, from the host against the development compose stack::

    uv run python import_concept_translations.py --host localhost --port 5433 --dry-run

Usage:
    import_concept_translations.py [options]

Options:
    --dotenv=<path>              Path to the database dotenv file.
    --host=<host>                PostgreSQL host override.
    --port=<port>                PostgreSQL port override.
    --database=<database>        PostgreSQL database override.
    --user=<user>                PostgreSQL user override.
    --password=<password>        PostgreSQL password override.
    --input-root=<path>          Locale directory override.
    --dry-run                    Validate catalogs without changing the database.
    -h --help                    Show this help.
"""

from __future__ import annotations

from pathlib import Path

from docpie import docpie

from concept_translations import (
    DEFAULT_LOCALE_ROOT,
    LANGUAGES,
    TRANSLATION_TABLE,
    ConceptTranslationError,
    connection_from_arguments,
    fetch_concepts,
    parse_po,
)


def read_catalogs(locale_root: Path) -> dict[str, dict[int, dict[str, str]]]:
    """Load the fixed English/German/Italian catalog set from one root.

    Requiring all three expected paths makes a missing locale an immediate
    error instead of allowing a partial import that would reintroduce the
    language inconsistency this tool is meant to repair. Returns the output of
    ``parse_po`` for each language, keyed by language code. Only files are read.
    """
    catalogs = {}
    for language in LANGUAGES:
        path = locale_root / language / "LC_MESSAGES" / "concepts.po"
        if not path.exists():
            raise ConceptTranslationError(f"Missing catalog: {path}")
        catalogs[language] = parse_po(path)
    return catalogs


def validate_catalogs(
    concepts: dict[int, dict[str, str]],
    catalogs: dict[str, dict[int, dict[str, str]]],
) -> None:
    """Check that PO entries and database Concepts form a complete match.

    Concept IDs are the identity check, and the English ``msgid`` must agree
    across the three catalogs. Missing or unknown IDs, empty translations, and
    inconsistent ``msgid`` values raise ``ConceptTranslationError``. The check
    runs before any write, and on its own it is the whole of ``--dry-run``.
    """
    expected_ids = set(concepts)
    for language in LANGUAGES:
        actual_ids = set(catalogs[language])
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing {sorted(missing)}")
            if extra:
                details.append(f"unknown {sorted(extra)}")
            raise ConceptTranslationError(
                f"{language} catalog does not match the database: {', '.join(details)}"
            )
        for concept_id, entry in catalogs[language].items():
            if not entry["msgstr"].strip():
                raise ConceptTranslationError(
                    f"{language} catalog has an empty translation for concept {concept_id}"
                )

    for concept_id in expected_ids:
        msgids = {catalogs[language][concept_id]["msgid"] for language in LANGUAGES}
        if len(msgids) != 1:
            raise ConceptTranslationError(
                f"Concept {concept_id} has inconsistent msgid values: {msgids}"
            )


def import_catalogs(connection, catalogs: dict[str, dict[int, dict[str, str]]]) -> int:
    """Upsert all three language rows and return the number of attempted rows.

    This function never commits. ``main`` runs it inside the psycopg2
    connection's ``with`` block, which commits the complete set on success and
    rolls it back on an exception. The ``ON CONFLICT`` clause decides whether
    each row is inserted or updated, keyed by language code and concept ID.
    Labels are stripped before they are written.
    """
    with connection.cursor() as cursor:
        count = 0
        for language in LANGUAGES:
            for concept_id, entry in catalogs[language].items():
                cursor.execute(
                    f"""
                    INSERT INTO {TRANSLATION_TABLE}
                        (language_code, label, master_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (language_code, master_id) DO UPDATE SET
                        label = EXCLUDED.label
                    """,
                    (language, entry["msgstr"].strip(), concept_id),
                )
                count += 1
    return count


def main() -> None:
    """Run the import: validate the catalogs, then upsert them.

    Invoked from the command line, as shown in the README. Options are parsed
    from the module docstring by docpie. Side effects are reads of the three PO
    files and the Concept table, then the upserts, unless ``--dry-run`` is set.
    It prints the number of validated concepts or imported rows. Validation
    failures raise ``ConceptTranslationError``, which is not caught here, so the
    process exits non-zero before any write.
    """
    args = docpie(__doc__)
    input_root = Path(args["--input-root"] or DEFAULT_LOCALE_ROOT)

    catalogs = read_catalogs(input_root)
    with connection_from_arguments(args) as connection:
        concepts = fetch_concepts(connection)
        validate_catalogs(concepts, catalogs)
        if args["--dry-run"]:
            print(
                f"validated {len(concepts)} concepts across {len(LANGUAGES)} languages"
            )
            return
        imported = import_catalogs(connection, catalogs)
        print(f"imported {imported} concept translations")


if __name__ == "__main__":
    main()
