#!/usr/bin/env python3
"""Export database Concept labels to locale/*/LC_MESSAGES/concepts.po.

This is the write-to-PO half of the round trip. It deliberately delegates
database access, language repair, and PO formatting to
``concept_translations.py`` so there is one implementation of the data
contract. In normal mode it exports only complete three-language data and
fails when the database is still incomplete; ``--machine-translate`` is an
explicit one-time bootstrap for the legacy rows whose language code is wrong.
The generated catalogs are reviewable handoff files, not an automatic license
to overwrite the database.

Usage:
    export_concept_translations.py [options]

Options:
    --dotenv=<path>              Path to the database dotenv file.
    --host=<host>                PostgreSQL host override.
    --port=<port>                PostgreSQL port override.
    --database=<database>        PostgreSQL database override.
    --user=<user>                PostgreSQL user override.
    --password=<password>        PostgreSQL password override.
    --output-root=<path>         Locale directory override.
    --machine-translate          Translate legacy all-English rows and fill gaps.
    --reuse-existing             Reuse unambiguous entries already in the PO files.
    --delay=<seconds>            Delay between public translation requests [default: 0.15].
    -h --help                    Show this help.
"""

from __future__ import annotations

from pathlib import Path

from docpie import docpie

from concept_translations import (
    DEFAULT_LOCALE_ROOT,
    LANGUAGES,
    bootstrap_catalogs,
    connection_from_arguments,
    fetch_concepts,
    parse_po,
    write_po,
)


def main() -> None:
    """Parse options, build catalogs, and write one PO file per language."""
    args = docpie(__doc__)
    output_root = Path(args["--output-root"] or DEFAULT_LOCALE_ROOT)
    delay = float(args["--delay"] or 0.15)

    existing_catalogs = None
    if args["--reuse-existing"]:
        existing_catalogs = {}
        for language in LANGUAGES:
            path = output_root / language / "LC_MESSAGES" / "concepts.po"
            if not path.exists():
                raise RuntimeError(f"Missing existing catalog: {path}")
            existing_catalogs[language] = parse_po(path)

    with connection_from_arguments(args) as connection:
        concepts = fetch_concepts(connection)
    catalogs = bootstrap_catalogs(
        concepts,
        args["--machine-translate"],
        delay,
        existing_catalogs=existing_catalogs,
    )
    for language in LANGUAGES:
        output = output_root / language / "LC_MESSAGES" / "concepts.po"
        write_po(output, language, catalogs[language])
        print(f"exported {len(catalogs[language])} concepts to {output}")


if __name__ == "__main__":
    main()