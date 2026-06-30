// static/js/i18n.js
//
// Lightweight, operative front-door localization for Applicant.
//
// User-facing strings tagged in the markup with `data-i18n="<key>"` are
// translated at runtime from a per-locale catalog under /static/locales/.
// The source locale is en-US (the literal text in the markup IS the en-US
// fallback), so a missing locale or a missing key degrades gracefully to the
// English already in the DOM — nothing ever disappears.
//
// This mirrors the engine-side catalog backend (applicant.i18n); the two share
// the same key namespace so a string is translated the same way on either side.

const SOURCE_LOCALE = 'en-US';
const STORAGE_KEY = 'applicant-locale';

let _locale = SOURCE_LOCALE;
let _catalog = {};

/** The active locale code (e.g. "en-US", "es-ES"). */
export function getLocale() {
  return _locale;
}

/** Translate a key, falling back to `fallback` (or the key) when absent. */
export function t(key, fallback) {
  if (_locale === SOURCE_LOCALE) return fallback != null ? fallback : key;
  const v = _catalog[key];
  return v != null ? v : (fallback != null ? fallback : key);
}

/**
 * Apply the active catalog to every `[data-i18n]` element under `root`.
 * The element's existing text is preserved as the fallback, so re-applying the
 * source locale is a no-op and an unknown key keeps the English already shown.
 */
export function applyTranslations(root = document) {
  const nodes = root.querySelectorAll('[data-i18n]');
  nodes.forEach((el) => {
    const key = el.getAttribute('data-i18n');
    if (!key) return;
    const translated = t(key, null);
    if (translated != null && translated !== key) {
      // Only the element's OWN leading text node is replaced, so nested
      // elements (counts, badges) inside the tagged node are left intact.
      const first = el.firstChild;
      if (first && first.nodeType === Node.TEXT_NODE) {
        first.textContent = translated;
      } else if (!el.children.length) {
        el.textContent = translated;
      } else {
        el.insertBefore(document.createTextNode(translated), el.firstChild);
      }
    }
  });
}

/** Load the catalog for `locale` from /static/locales/<locale>.json. */
async function _loadCatalog(locale) {
  if (locale === SOURCE_LOCALE) return {};
  try {
    const resp = await fetch(`/static/locales/${encodeURIComponent(locale)}.json`, {
      credentials: 'same-origin',
    });
    if (!resp.ok) return {};
    const data = await resp.json();
    if (data && typeof data === 'object') {
      delete data._meta;
      return data;
    }
  } catch (_) { /* offline / missing locale → English fallback */ }
  return {};
}

/** Switch the active locale, load its catalog, and re-apply to the page. */
export async function setLocale(locale) {
  _locale = locale || SOURCE_LOCALE;
  try { localStorage.setItem(STORAGE_KEY, _locale); } catch (_) { /* private mode */ }
  _catalog = await _loadCatalog(_locale);
  document.documentElement.setAttribute('lang', _locale.split('-')[0] || 'en');
  applyTranslations();
}

/** Resolve the preferred locale: saved choice → browser language → source. */
function _preferredLocale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return saved;
  } catch (_) { /* ignore */ }
  return SOURCE_LOCALE; // browser-language auto-pick is opt-in; default English
}

/** Initialize i18n on load: pick the locale and localize the static markup. */
export async function initI18n() {
  await setLocale(_preferredLocale());
}

// Apply on initial load so any non-English saved choice localizes the static
// shell immediately (English is already in the DOM, so this is a no-op for the
// source locale and never blocks first paint).
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initI18n(); }, { once: true });
  } else {
    initI18n();
  }
}

const i18nModule = { getLocale, setLocale, t, applyTranslations, initI18n };
export default i18nModule;

// Expose for any non-importing module that wants to switch locales.
if (typeof window !== 'undefined') {
  window.applicantI18n = i18nModule;
}
