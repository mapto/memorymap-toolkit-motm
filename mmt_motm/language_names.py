"""Localized display names for extraction quote languages.

The language names use their own gettext domain because they are data labels,
not application UI messages. Keeping this mapping and its catalogs separate
from the main Django catalog makes the language list reusable and maintainable.
"""

from __future__ import annotations

from gettext import translation
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils.translation import get_language


LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "it": "Italian",
    "es": "Spanish",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "cs": "Czech",
    "ru": "Russian",
    "uk": "Ukrainian",
    "he": "Hebrew",
    "yi": "Yiddish",
    "ar": "Arabic",
    "tr": "Turkish",
    "hu": "Hungarian",
    "ro": "Romanian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sr": "Serbian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "el": "Greek",
    "da": "Danish",
    "sv": "Swedish",
    "no": "Norwegian",
    "fi": "Finnish",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
}


@lru_cache(maxsize=None)
def _language_translation(language: str):
    """Load the dedicated language-name catalog for an active language."""
    localedir = Path(str(settings.LOCALE_PATHS[0]))
    return translation(
        "languages",
        localedir=str(localedir),
        languages=[language, "en"],
        fallback=True,
    )


def language_name(code: str) -> str:
    """Return the localized display name for an ISO language code."""
    if not code:
        return ""
    source_name = LANGUAGE_NAMES.get(code)
    if source_name is None:
        return code
    language = (get_language() or settings.LANGUAGE_CODE).split("-")[0]
    return _language_translation(language).gettext(source_name)
