"""Internationalization (i18n) infrastructure (issue #250).

Provides string extraction markers and a lightweight translation lookup for
user-facing strings. Default locale is en-US with all strings returned as-is;
additional locales can be loaded from JSON translation files.

Usage:

    from applicant.core.i18n import _, get_locale, load_translations

    # Mark strings for translation (extracted by xgettext-equivalent tooling)
    greeting = _("Hello, welcome to the application assistant")

    # Load a specific locale
    load_translations("de-DE", {"Hello, welcome...": "Hallo, willkommen..."})

    # Switch locale
    from applicant.core.i18n import set_locale
    set_locale("de-DE")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import local

# Thread-local storage for the active locale.
_tls = local()
_tls.locale: str = "en-US"
_tls.translations: dict[str, dict[str, str]] = {"en-US": {}}


def _active_translations() -> dict[str, str]:
    """Return the translation dict for the current thread's locale."""
    return _tls.translations.get(_tls.locale, {})


def _(message: str) -> str:
    """Mark a user-facing string for translation and look up the translation.

    If a translation exists for the active locale it is returned; otherwise the
    original English message is used as the fallback.

    This is the primary extraction marker — tooling scans for all calls to _()
    to build the translatable string catalog.
    """
    if _tls.locale == "en-US" or not message:
        return message
    translations = _active_translations()
    translated = translations.get(message)
    return translated if translated is not None else message


def _n(singular: str, plural: str, count: int) -> str:
    """Plural-form-aware translation marker (basic English: singular/plural)."""
    if count == 1:
        return _(singular)
    translations = _active_translations()
    translated = translations.get(plural)
    return (translated if translated is not None else plural).format(count=count)


def get_locale() -> str:
    """Return the active locale string (e.g. "en-US", "de-DE")."""
    return _tls.locale


def set_locale(locale: str) -> None:
    """Switch the active locale for the current thread.

    Purely additive — strings not present in the new locale's catalog fall back
    to English. A missing or empty locale resets to en-US.
    """
    if not locale:
        locale = "en-US"
    _tls.locale = locale
    # Ensure a translations dict exists for this locale (may be empty).
    if locale not in _tls.translations:
        _tls.translations[locale] = {}


def load_translations(
    locale: str,
    translations: dict[str, str],
    *,
    merge: bool = True,
) -> None:
    """Load a translation dictionary for *locale*.

    Args:
        locale: The locale key (e.g. "de-DE", "fr-FR", "es-ES").
        translations: Mapping of English source strings -> translated strings.
        merge: If True (default), new translations are merged with any existing
            ones for this locale. If False, the existing dict is replaced.
    """
    if locale not in _tls.translations:
        _tls.translations[locale] = {}
    if merge:
        _tls.translations[locale].update(translations)
    else:
        _tls.translations[locale] = dict(translations)


def load_translations_file(locale: str, filepath: str | Path) -> int:
    """Load translations from a JSON file.

    The file is expected to contain a flat JSON object mapping English source
    strings to translated strings:

        {"Hello": "Hallo", "Goodbye": "Tschüss"}

    Returns the number of translation entries loaded.
    """
    path = Path(filepath)
    if not path.is_file():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return 0
    load_translations(locale, data)
    return len(data)


#: Default translations directory (relative to the project root).
_TRANSLATIONS_DIR = Path(__file__).resolve().parents[3] / "translations"


def discover_translations() -> list[str]:
    """Scan the translations directory for available locale JSON files.

    Returns a sorted list of available locale codes (e.g. ["de-DE", "es-ES"]).
    Files must be named <locale>.json (e.g. de-DE.json).
    """
    if not _TRANSLATIONS_DIR.is_dir():
        return []
    locales: list[str] = []
    for f in sorted(_TRANSLATIONS_DIR.iterdir()):
        if f.suffix.lower() == ".json" and f.stem and "-" in f.stem:
            locales.append(f.stem)
    return locales


#: Mark a user-facing message for extraction without immediate lookup.
#: Useful for building translation catalogs programmatically.
def mark(message: str) -> str:
    """Mark *message* as translatable without looking it up (extraction aid)."""
    return message


#: Plural-form-aware extraction marker.
def mark_n(singular: str, plural: str) -> tuple[str, str]:
    """Mark a plural pair for extraction."""
    return (singular, plural)


# Convenience: bulk-extract all user-facing strings from a module's namespace.
# These are registered as translatable but not translated in en-US.
CATALOG: dict[str, str] = {}
