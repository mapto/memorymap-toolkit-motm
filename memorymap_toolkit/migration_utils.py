"""Shared helpers for hand-edited migrations.

``AlterModelBases`` is a state-only migration operation used when converting an
existing plain ``models.Model`` into a django-parler ``TranslatableModel``.
Parler's ``TranslationsForeignKey`` requires the "shared" model to inherit from
``parler.models.TranslatableModel`` when Django resolves the relation while
replaying migration history, but that base class is not otherwise recorded
anywhere in the migration graph. This operation patches the model's recorded
bases in the migration state (it has no effect on the database schema).
"""
from django.db.migrations.operations.base import Operation


class AlterModelBases(Operation):
    reduces_to_sql = False
    reversible = True

    def __init__(self, name, bases):
        self.name = name
        self.bases = bases

    def state_forwards(self, app_label, state):
        model_state = state.models[app_label, self.name.lower()]
        model_state.bases = self.bases
        # Force models relying on this state to be re-rendered.
        state.reload_model(app_label, self.name.lower(), delay=True)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def describe(self):
        return f"Alter model bases for {self.name}"

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name.lower()}_bases"
