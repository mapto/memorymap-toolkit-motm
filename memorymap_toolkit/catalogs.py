"""Helpers for loading the project's data-specific gettext catalogs."""

from functools import lru_cache
import gettext

from django.conf import settings
from django.utils import translation


@lru_cache(maxsize=None)
def _catalog(domain, language_code):
    locale_root = str(settings.LOCALE_PATHS[0])
    return gettext.translation(
        domain,
        localedir=locale_root,
        languages=[language_code],
        fallback=True,
    )


def catalog_pgettext(domain, context, message, language_code=None):
    """Translate a context-specific data value with the active locale."""
    language_code = language_code or translation.get_language() or settings.LANGUAGE_CODE
    catalog = _catalog(domain, language_code)
    contextual_key = f"{context}\x04{message}"
    if contextual_key in catalog._catalog:
        return catalog._catalog[contextual_key]
    return message


def localized_event_description(event, language_code=None):
    return catalog_pgettext(
        "events",
        f"event:{event.pk}",
        event.description,
        language_code,
    )


def localized_concept_label(concept, language_code=None):
    language_code = language_code or translation.get_language() or settings.LANGUAGE_CODE
    return concept.safe_translation_getter(
        "label",
        language_code=language_code,
        any_language=False,
    )


def localized_person_description(person, language_code=None):
    return catalog_pgettext(
        "people",
        "prosecuted-group",
        person.description,
        language_code,
    )


def localized_person_field(person, field_name, language_code=None):
    value = getattr(person, field_name, "")
    if not value:
        return value
    return catalog_pgettext(
        "people",
        f"person:{field_name}",
        value,
        language_code,
    )
