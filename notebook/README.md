Scripts for preprocessing [Minors on the Move](https://prinminorsonthemove.wordpress.com) project data.

To get this running you need to install [uv](https://docs.astral.sh/uv/getting-started/installation/).

Then simply run

    uv run jupyter lab

If making changes, before committing, run:

    uv run ruff format
    uv run ruff check --fix
    uv run pytest --doctest-modules

## Concept translations

Concept labels are stored by django-parler in PostgreSQL and are maintained
separately from the application UI catalog. The export and import commands use
the database settings from the repository `.env` file and read or write:

    locale/en/LC_MESSAGES/concepts.po
    locale/de/LC_MESSAGES/concepts.po
    locale/it/LC_MESSAGES/concepts.po

When running from the host with the development compose stack, PostgreSQL is
exposed on port 5433:

    uv run python export_concept_translations.py --host localhost --port 5433 --machine-translate
    uv run python import_concept_translations.py --host localhost --port 5433 --dry-run
    uv run python import_concept_translations.py --host localhost --port 5433

The `--machine-translate` option is intended for the initial repair of the
legacy all-English rows. It uses the public MyMemory service to fill missing
English, German, and Italian labels; review the generated PO files before
importing them. Later exports can omit that option and require all three
languages to already exist in the database.
