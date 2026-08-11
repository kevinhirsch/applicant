import pytest

from applicant.core.i18n import (
    _,
    _n,
    get_locale,
    set_locale,
    load_translations,
    mark,
    mark_n,
    CATALOG,
    _tls,
)


@pytest.fixture(autouse=True)
def reset_i18n_state():
    """Reset thread-local state before each test."""
    _tls.locale = "en-US"
    _tls.translations = {"en-US": {}}
    yield


class TestSingleUnderscore:
    """Tests for _(message) — primary extraction marker."""

    def test_en_uses_message_as_is(self):
        """When locale is en-US, _(x) returns x."""
        assert _("Hello") == "Hello"

    def test_empty_string_returns_empty(self):
        """Empty message returns empty regardless of locale."""
        assert _("") == ""

    def test_returns_message_when_not_translated(self):
        """When no translation exists for a non-en-US locale, original is returned."""
        set_locale("de-DE")
        assert _("Hello") == "Hello"

    def test_returns_translation_when_available(self):
        """When a translation exists for the active locale, it is returned."""
        load_translations("de-DE", {"Hello": "Hallo"})
        set_locale("de-DE")
        assert _("Hello") == "Hallo"

    def test_translated_string_with_multiple_entries(self):
        """Multiple translation entries are all looked up correctly."""
        load_translations("fr-FR", {"Yes": "Oui", "No": "Non"})
        set_locale("fr-FR")
        assert _("Yes") == "Oui"
        assert _("No") == "Non"

    def test_partial_translation_falls_back_to_original(self):
        """Untranslated keys fall back to the English message."""
        load_translations("de-DE", {"Hello": "Hallo"})
        set_locale("de-DE")
        assert _("Goodbye") == "Goodbye"


class TestN:
    """Tests for _n(singular, plural, count) — plural form marker."""

    def test_singular_count_1_returns_singular(self):
        """count==1 returns _(singular), which is the original for en-US."""
        assert _n("item", "items", 1) == "item"

    def test_plural_count_0_returns_plural(self):
        """count!=1 returns plural formatted with count."""
        result = _n("item", "items", 0)
        assert result == "items"

    def test_plural_count_2_returns_plural_with_count(self):
        """count>1 returns plural string with {count} substituted."""
        result = _n("item", "items", 2)
        assert result == "items"

    def test_plural_with_translated_plural(self):
        """When plural is translated, use the translated version with count."""
        load_translations("de-DE", {"items": "{count} Artikel"})
        set_locale("de-DE")
        result = _n("item", "items", 3)
        assert result == "3 Artikel"

    def test_singular_with_translation(self):
        """Singular path uses _(singular) which can be translated."""
        load_translations("de-DE", {"item": "Artikel"})
        set_locale("de-DE")
        assert _n("item", "items", 1) == "Artikel"


class TestGetLocale:
    """Tests for get_locale()."""

    def test_default_is_en_us(self):
        """Default locale is en-US."""
        assert get_locale() == "en-US"

    def test_after_set_locale(self):
        """get_locale returns locale set by set_locale."""
        set_locale("de-DE")
        assert get_locale() == "de-DE"

    def test_after_set_locale_fr_fr(self):
        """Another locale round-trips correctly."""
        set_locale("fr-FR")
        assert get_locale() == "fr-FR"


class TestSetLocale:
    """Tests for set_locale(locale)."""

    def test_switches_locale(self):
        """set_locale changes the active locale."""
        set_locale("de-DE")
        assert get_locale() == "de-DE"

    def test_empty_locale_resets_to_en_us(self):
        """An empty/ falsy locale resets to en-US."""
        set_locale("de-DE")
        set_locale("")
        assert get_locale() == "en-US"

    def test_none_locale_resets_to_en_us(self):
        """None locale resets to en-US."""
        set_locale("de-DE")
        set_locale(None)
        assert get_locale() == "en-US"

    def test_creates_empty_translations_dict(self):
        """Setting a new locale initialises an empty translations dict."""
        set_locale("it-IT")
        assert get_locale() == "it-IT"
        assert _("Hello") == "Hello"


class TestLoadTranslations:
    """Tests for load_translations(locale, translations, merge=True)."""

    def test_load_and_use(self):
        """Loaded translations are used when the locale is active."""
        load_translations("de-DE", {"Hello": "Hallo"})
        set_locale("de-DE")
        assert _("Hello") == "Hallo"

    def test_load_then_no_merge_replaces(self):
        """merge=False replaces existing translations for that locale."""
        load_translations("de-DE", {"Hello": "Hallo", "Goodbye": "Tschüss"})
        load_translations("de-DE", {"Hello": "Servus"}, merge=False)
        set_locale("de-DE")
        assert _("Hello") == "Servus"
        assert _("Goodbye") == "Goodbye"  # replaced dict lost Goodbye

    def test_merge_true_adds_without_losing(self):
        """merge=True preserves existing entries and adds new ones."""
        load_translations("de-DE", {"Hello": "Hallo"})
        load_translations("de-DE", {"Goodbye": "Tschüss"}, merge=True)
        set_locale("de-DE")
        assert _("Hello") == "Hallo"
        assert _("Goodbye") == "Tschüss"

    def test_load_twice_last_merge_wins(self):
        """Merge=True updates existing keys with newer values."""
        load_translations("de-DE", {"Hello": "Hallo"})
        load_translations("de-DE", {"Hello": "Servus"}, merge=True)
        set_locale("de-DE")
        assert _("Hello") == "Servus"


class TestMark:
    """Tests for mark(message) — extraction marker."""

    def test_returns_message(self):
        """mark returns the input message unchanged."""
        assert mark("Hello") == "Hello"

    def test_returns_empty_string(self):
        """mark returns empty string unchanged."""
        assert mark("") == ""

    def test_does_not_affect_active_locale(self):
        """mark does not alter locale or translations."""
        mark("Hello")
        assert get_locale() == "en-US"


class TestMarkN:
    """Tests for mark_n(singular, plural) — plural extraction marker."""

    def test_returns_tuple(self):
        """mark_n returns a tuple (singular, plural)."""
        assert mark_n("item", "items") == ("item", "items")


class TestCatalog:
    """Tests for the CATALOG module constant."""

    def test_catalog_is_empty_dict(self):
        """CATALOG is an empty dict."""
        assert CATALOG == {}


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_set_locale_then_get_locale_then_translate(self):
        """Full round-trip: set locale, load translations, translate, get locale back."""
        load_translations("es-ES", {"Hello": "Hola"})
        set_locale("es-ES")
        assert get_locale() == "es-ES"
        assert _("Hello") == "Hola"

    def test_switch_back_to_en_us_loses_translation(self):
        """Switching back to en-US returns original strings."""
        load_translations("de-DE", {"Hello": "Hallo"})
        set_locale("de-DE")
        assert _("Hello") == "Hallo"
        set_locale("en-US")
        assert _("Hello") == "Hello"

    def test_multiple_locales_persist_separately(self):
        """Translations for different locales are kept separate."""
        load_translations("de-DE", {"Hello": "Hallo"})
        load_translations("fr-FR", {"Hello": "Bonjour"})
        set_locale("de-DE")
        assert _("Hello") == "Hallo"
        set_locale("fr-FR")
        assert _("Hello") == "Bonjour"
        set_locale("en-US")
        assert _("Hello") == "Hello"
