from django.db import migrations


# Duplicate concept IDs are data-specific: these rows were created from the
# same labels by separate imports. The right-hand ID is the canonical record;
# the labels below make the historical ID choice auditable.
MERGES = {
    18: 2,    # Father -> Father
    372: 64,  # Immigration -> Immigration
    404: 80,  # Work -> Work
    355: 107, # Old homeland -> Old homeland
    359: 107, # Old homeland -> Old homeland
    384: 150, # My New Home -> My New Home
    390: 161, # The journey back -> The journey back
}

# These are not duplicate masters. They are language-label collisions where
# the translation had assigned the wrong meaning to a distinct concept.
TRANSLATION_CORRECTIONS = {
    (101, "de"): "Englisch",  # English, not German
    (200, "de"): "Boot",      # Boat, distinct from Ship
    (200, "it"): "Barca",     # Boat, distinct from Ship
}


def merge_concepts(apps, schema_editor):
    Concept = apps.get_model("mmt_motm", "Concept")
    Event = apps.get_model("mmt_motm", "Event")
    Extraction = apps.get_model("mmt_motm", "Extraction")
    LocationPoint = apps.get_model("mmt_motm", "LocationPoint")
    Translation = apps.get_model("mmt_motm", "ConceptTranslation")

    # Correct labels before merging so the surviving taxonomy remains
    # distinguishable in every supported language.
    for (concept_id, language_code), label in TRANSLATION_CORRECTIONS.items():
        Translation.objects.filter(
            master_id=concept_id,
            language_code=language_code,
        ).update(label=label)

    for duplicate_id, canonical_id in MERGES.items():
        duplicate = Concept.objects.filter(pk=duplicate_id).first()
        canonical = Concept.objects.filter(pk=canonical_id).first()
        if duplicate is None or canonical is None:
            continue

        # Add relations before deleting the duplicate; add() is idempotent and
        # preserves links already attached to the canonical concept.
        for event in Event.objects.filter(concepts=duplicate):
            event.concepts.add(canonical)
        for extraction in Extraction.objects.filter(concepts=duplicate):
            extraction.concepts.add(canonical)

        LocationPoint.objects.filter(concept_id=duplicate_id).update(
            concept_id=canonical_id
        )
        Concept.objects.filter(parent_id=duplicate_id).update(
            parent_id=canonical_id
        )

        if not canonical.icon and duplicate.icon:
            canonical.icon = duplicate.icon
            canonical.save(update_fields=["icon"])

        # This also removes the duplicate's translation rows. The canonical
        # master ID is retained so URLs and external references stay stable.
        duplicate.delete()


def reverse_merge(apps, schema_editor):
    # The source records and their original relation split are not recoverable
    # once the merge has run, so this data migration is intentionally forward-only.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("mmt_motm", "0019_person_metadata_fields"),
    ]

    operations = [
        migrations.RunPython(merge_concepts, reverse_merge),
    ]