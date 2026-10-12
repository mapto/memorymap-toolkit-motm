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

    uv run python export_concept_translations.py --host localhost --port 5433 --machine-translate --reuse-existing
    uv run python import_concept_translations.py --host localhost --port 5433 --dry-run
    uv run python import_concept_translations.py --host localhost --port 5433

The `--machine-translate` option is intended for the initial repair of the
legacy all-English rows. `--reuse-existing` preserves complete, unambiguous
translations already present in the catalogs and limits machine translation
to genuinely new or ambiguous labels. The exporter retries transient service
failures. Review the generated PO files before importing them. Later exports
can omit both options and require all three languages to already exist in the
database.

## Location workbook rebuild

The standard `import.sh` pipeline rebuilds `locations.xlsx` during the
chronotopi import. To run the same rebuild by itself:

    uv run python rebuild_locations.py

The rebuild preserves the existing URL columns, adds `wider_region` and
`coordinate_source`, and resolves coordinates in this order: chronotopi
coordinates, GeoNames, Wikidata, the local geocoder, and Nominatim as the
external fallback. It uses the GO taxonomy for containment, so addresses are
assigned to cities, cities to areas/countries, and countries to the GO
supranational category where those concepts exist. Non-location artifacts such
as route descriptions and URL-only organization entries are omitted rather than
written as coordinate-less rows. Create a dated copy of `locations.xlsx` before
running the rebuild or `import.sh`.

The `super_region` column is transliterated to Latin text, while
`wider_region` retains the full taxonomy path used to derive containment.
