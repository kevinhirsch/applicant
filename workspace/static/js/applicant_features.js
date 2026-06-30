// static/js/applicant_features.js
//
// Front-door feature-state consumption layer for Applicant-mapped sections.
//
// This is the JS counterpart of the Python feature layer in
// src/applicant_features.py. It fetches /api/applicant/features and provides
// reusable functions for gating UI elements based on engine dormant-surface
// status and section state.
//
// All functions degrade gracefully (never throw) so dead UI never causes a 500.

const API_BASE = window.location.origin;

// Cached feature state for the page session.
let _featureCache = null;

/**
 * Fetch the Applicant feature state from the server.
 * Cached for the page session; never throws.
 * @returns {Promise<{engine_available: boolean, engine_url: string, sections: object}>}
 */
export async function fetchFeatureState() {
  if (_featureCache) return _featureCache;
  try {
    const r = await fetch(`${API_BASE}/api/applicant/features`, {
      credentials: 'same-origin',
    });
    if (!r.ok) return { engine_available: false, engine_url: '', sections: {} };
    const data = await r.json();
    _featureCache = data;
    return data;
  } catch (_) {
    return { engine_available: false, engine_url: '', sections: {} };
  }
}

/**
 * Invalidate the cached feature state so the next call re-fetches.
 */
export function invalidateFeatureCache() {
  _featureCache = null;
}

/**
 * Check whether a section is in the given state.
 * @param {string} sectionKey
 * @param {string} state - 'active' | 'configured' | 'locked' | 'disabled'
 * @returns {Promise<boolean>}
 */
export async function sectionInState(sectionKey, state) {
  try {
    const features = await fetchFeatureState();
    const sec = features.sections && features.sections[sectionKey];
    return !!(sec && sec.state === state);
  } catch (_) {
    return false;
  }
}

/**
 * Check whether a section is active (engine reachable + backing live).
 * @param {string} sectionKey
 * @returns {Promise<boolean>}
 */
export async function isSectionActive(sectionKey) {
  return sectionInState(sectionKey, 'active');
}

/**
 * Return the full section descriptor for a given key, or null.
 * @param {string} sectionKey
 * @returns {Promise<object|null>}
 */
export async function getSection(sectionKey) {
  try {
    const features = await fetchFeatureState();
    return features.sections && features.sections[sectionKey] || null;
  } catch (_) {
    return null;
  }
}

/**
 * Return the list of nav_ids for an active section, or [] if locked/disabled.
 * @param {string} sectionKey
 * @returns {Promise<string[]>}
 */
export async function getActiveNavIds(sectionKey) {
  try {
    const features = await fetchFeatureState();
    const sec = features.sections && features.sections[sectionKey];
    if (sec && sec.state === 'active') return sec.nav_ids || [];
    return [];
  } catch (_) {
    return [];
  }
}
