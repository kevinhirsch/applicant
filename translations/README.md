# Translations

User-facing string translations for the Applicant engine.

## Structure

Each locale gets a JSON file named `<locale>.json` (e.g. `de-DE.json`, `es-ES.json`).
The file contains a flat object mapping English source strings to the translated equivalent:

```json
{
  "Hello, welcome to the application assistant": "Hallo, willkommen beim Bewerbungsassistenten",
  "Approve": "Genehmigen",
  "Decline": "Ablehnen"
}
```

## Extraction

User-facing strings are marked in Python code with `_()` (from `applicant.core.i18n`):

```python
from applicant.core.i18n import _
message = _("Approve")
```

Run `python -m applicant.core.i18n_extract` to scan source files and produce
a `translations/template.pot` file for translators.

## Loading

Translations are loaded automatically at startup from the `translations/` directory.
The active locale defaults to `en-US` (all strings returned as-is). Switch locale
via:

```python
from applicant.core.i18n import set_locale
set_locale("de-DE")
```

Strings not found in the active locale's catalog fall back to English.
