"""First-party localization framework for the engine (issues #194, #250).

This package is the engine-side translation backend so user-facing parsing and
strings are not hardwired to US English. It is a thin, stable public surface over
the real catalog-backed implementation in :mod:`applicant.core.i18n` (lift-and-shift
of the existing backend rather than a second implementation):

* ``_(message)`` / ``_n(singular, plural, count)`` — gettext-style translation
  markers that look up the active locale's catalog and fall back to English;
* ``set_locale`` / ``get_locale`` — switch the active locale (thread-local);
* ``load_translations`` / ``load_translations_file`` — register a locale catalog
  from a dict or a JSON resource file;
* ``discover_translations`` — enumerate the shipped locale resources.

The catalog resources live under ``translations/<locale>.json`` and the
front-door's ``workspace/static/locales/<locale>.json`` mirror.

Example::

    from applicant.i18n import _, set_locale, load_translations

    load_translations("fr-FR", {"Connect a model": "Connecter un modèle"})
    set_locale("fr-FR")
    _("Connect a model")  # -> "Connecter un modèle"
"""

from __future__ import annotations

from applicant.core.i18n import (
    CATALOG,
    _,
    _n,
    discover_translations,
    get_locale,
    load_translations,
    load_translations_file,
    mark,
    mark_n,
    set_locale,
)

# A gettext-style alias so callers expecting the classic name find it here too.
gettext = _
ngettext = _n

__all__ = [
    "_",
    "_n",
    "gettext",
    "ngettext",
    "set_locale",
    "get_locale",
    "load_translations",
    "load_translations_file",
    "discover_translations",
    "mark",
    "mark_n",
    "CATALOG",
]
