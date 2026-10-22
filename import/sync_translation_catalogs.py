"""Synchronize model-backed gettext catalogs with the imported data.

The ``concepts`` and ``events`` catalogs are not extracted from Python source
code. Their messages are database rows identified by ``concept:<id>`` and
``event:<id>`` contexts. The importer normally creates only the source
language Parler row, so existing PO translations are retained by context while
new or removed model rows are reflected in the catalogs.

The synchronization flow is:

1. Bootstrap Django and read the configured ``Concept`` and ``Event``
    translation tables without applying Parler's language fallback.
2. Read the existing context-keyed PO entries for each configured language.
3. Reconcile current model IDs with those entries. The current source text is
    written as ``msgid``; existing ``msgstr`` values are retained by context,
    while an actual model translation takes precedence for its language.
4. Rewrite each catalog with a stable header and ID ordering, dropping entries
    for deleted model rows.
5. Let ``import.sh`` run ``manage.py compilemessages`` so the refreshed PO
    catalogs are available at runtime as MO files.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "memorymap_toolkit.settings.production"
)

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from mmt_motm.models import Concept, Event  # noqa: E402


CATALOGS = {
    "concepts": (Concept, "label", "concept"),
    "events": (Event, "description", "event"),
}
FIELD_RE = re.compile(r"^(msgctxt|msgid|msgstr) (.+)$")


def decode_po_value(value: str) -> str:
    """Decode one quoted PO string without evaluating arbitrary code."""
    decoded = ast.literal_eval(value)
    if not isinstance(decoded, str):
        raise ValueError(f"PO value is not a string: {value}")
    return decoded


def read_catalog(path: Path, context_prefix: str) -> dict[int, dict[str, str]]:
    """Read ID-keyed entries from one data catalog."""
    if not path.exists():
        return {}

    entries: dict[int, dict[str, str]] = {}
    current: dict[str, str] = {}
    active_field = None

    def flush() -> None:
        nonlocal current
        context = current.get("msgctxt", "")
        if context.startswith(f"{context_prefix}:"):
            try:
                object_id = int(context.removeprefix(f"{context_prefix}:"))
            except ValueError as error:
                raise ValueError(f"Invalid context in {path}: {context}") from error
            if object_id in entries:
                raise ValueError(f"Duplicate context in {path}: {context}")
            entries[object_id] = {
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
        matched = FIELD_RE.match(line)
        if matched:
            active_field = matched.group(1)
            current[active_field] = decode_po_value(matched.group(2))
            continue
        if line.startswith('"') and active_field:
            current[active_field] += decode_po_value(line)
            continue
        raise ValueError(f"Unsupported PO line in {path}: {raw_line}")
    flush()
    return entries


def po_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def po_field(name: str, value: str) -> list[str]:
    if "\n" not in value:
        return [f"{name} {po_value(value)}"]
    return [f'{name} ""'] + [po_value(line) for line in value.splitlines(keepends=True)]


def header(path: Path, domain: str, language: str) -> list[str]:
    """Keep an existing header stable, or create a valid new one."""
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0] == 'msgid ""':
            return lines[: lines.index("") if "" in lines else len(lines)]

    language_name = dict(settings.LANGUAGES).get(language, language)
    metadata = [
        f"Project-Id-Version: memorymap-toolkit-{domain}\n",
        "Report-Msgid-Bugs-To: \n",
        "PO-Revision-Date: 1970-01-01 00:00+0000\n",
        "Last-Translator: \n",
        f"Language-Team: {language_name}\n",
        f"Language: {language}\n",
        "MIME-Version: 1.0\n",
        "Content-Type: text/plain; charset=UTF-8\n",
        "Content-Transfer-Encoding: 8bit\n",
        "Plural-Forms: nplurals=2; plural=(n != 1);\n",
    ]
    return ['msgid ""', 'msgstr ""'] + [po_value(value) for value in metadata]


def model_translations(model, field: str) -> tuple[list[int], dict[int, dict[str, str]]]:
    """Return model IDs and their actual Parler rows without fallback values."""
    translation_model = model._parler_meta.root_model
    translations: dict[int, dict[str, str]] = defaultdict(dict)
    for row in translation_model.objects.values("master_id", "language_code", field):
        value = row[field] or ""
        if value:
            translations[row["master_id"]][row["language_code"]] = value

    object_ids = list(model.objects.order_by("pk").values_list("pk", flat=True))
    return object_ids, translations


def synchronize_catalog(
    root: Path,
    domain: str,
    model,
    field: str,
    context_prefix: str,
    languages: tuple[str, ...],
) -> int:
    """Reconcile one model's translations with its context-keyed PO catalogs.

    The model primary key is the stable identity for an entry. This lets the
    function update a source ``msgid`` when a label or description changes,
    retain reviewed translations when the database has no target-language row,
    and remove stale entries for deleted objects. Catalogs are written only
    when their content changes.

    Args:
        root: Locale directory containing one subdirectory per language.
        domain: Gettext domain, such as ``concepts`` or ``events``.
        model: Parler model whose objects provide the catalog entries.
        field: Translated model field used for the message text.
        context_prefix: PO context prefix matching the model, such as
            ``concept`` or ``event``.
        languages: Language codes whose catalogs should be synchronized.

    Returns:
        The number of current model objects represented in the catalogs.

    Raises:
        ValueError: If a PO context is malformed or a model object has no
            source-language translation.
    """
    object_ids, translations = model_translations(model, field)
    paths = {
        language: root / language / "LC_MESSAGES" / f"{domain}.po"
        for language in languages
    }
    existing = {
        language: read_catalog(path, context_prefix)
        for language, path in paths.items()
    }

    entries_by_language = {language: {} for language in languages}
    missing_source = []
    for object_id in object_ids:
        values = translations.get(object_id, {})
        source_language = next(
            (language for language in ("en", *languages) if values.get(language)),
            None,
        )
        if source_language is None:
            missing_source.append(object_id)
            continue

        source = values[source_language]
        for language in languages:
            old_translation = existing[language].get(object_id, {}).get("msgstr", "")
            if language == source_language:
                translated = old_translation or source
            else:
                translated = values.get(language) or old_translation
            entries_by_language[language][object_id] = {
                "msgid": source,
                "msgstr": translated or "",
            }

    if missing_source:
        raise ValueError(
            f"{domain} rows without a source-language translation: {missing_source}"
        )

    for language, path in paths.items():
        lines = header(path, domain, language)
        for object_id in sorted(entries_by_language[language]):
            entry = entries_by_language[language][object_id]
            lines.extend(
                [
                    "",
                    f'msgctxt "{context_prefix}:{object_id}"',
                    *po_field("msgid", entry["msgid"]),
                    *po_field("msgstr", entry["msgstr"]),
                ]
            )
        content = "\n".join(lines) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")

    return len(object_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--locale-root",
        type=Path,
        default=None,
        help="Locale directory; defaults to Django's LOCALE_PATHS entry.",
    )
    args = parser.parse_args()
    root = args.locale_root or Path(str(settings.LOCALE_PATHS[0]))
    languages = tuple(code for code, _ in settings.LANGUAGES)

    for domain, (model, field, context_prefix) in CATALOGS.items():
        count = synchronize_catalog(
            root, domain, model, field, context_prefix, languages
        )
        print(f"synchronized {count} {domain} messages")


if __name__ == "__main__":
    main()