// static/js/applicantEmail.js
//
// JS consumer for the /api/applicant/email/* proxy routes.
//
// Provides standalone functions for digest, feedback, and presence operations
// backed by the engine's digest + feedback routers. These can be imported by
// any surface (the Email library popup, the Portal home base, etc.) without
// coupling to the emailLibrary DOM.
//
// All functions degrade gracefully (never throw), returning a well-shaped
// degraded payload on failure.

import { _fetchJSON, _post } from './applicantCore.js';

const API_BASE = window.location.origin;

async function _api(path, { method = 'GET', body = null } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body != null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${API_BASE}/api/applicant/email${path}`, opts);
  let payload = null;
  try { payload = await r.json(); } catch (_) { payload = null; }
  if (!r.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `Request failed (${r.status})`;
    const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
    err.status = r.status;
    throw err;
  }
  return payload;
}

/**
 * List campaigns for digest selection.
 * @returns {Promise<Array<{id: string, name: string}>>}
 */
export async function listCampaigns() {
  try {
    const data = await _api('/campaigns');
    return (data && Array.isArray(data.campaigns)) ? data.campaigns : [];
  } catch (_) {
    return [];
  }
}

/**
 * Fetch the daily digest for a campaign.
 * @param {string} campaignId
 * @returns {Promise<object>}
 */
export async function fetchDigest(campaignId) {
  if (!campaignId) return { rows: [], empty: true };
  try {
    return await _api(`/digest/${encodeURIComponent(campaignId)}`);
  } catch (_) {
    return { rows: [], empty: true, error: true };
  }
}

/**
 * Fetch the engine's rendered digest email payload (subject + body).
 * @param {string} campaignId
 * @returns {Promise<object>}
 */
export async function fetchDigestEmail(campaignId) {
  if (!campaignId) return {};
  try {
    return await _api(`/digest/${encodeURIComponent(campaignId)}/email`);
  } catch (_) {
    return {};
  }
}

/**
 * Re-send / deliver the digest across configured channels.
 * @param {string} campaignId
 * @returns {Promise<object>}
 */
export async function deliverDigest(campaignId) {
  if (!campaignId) return { ok: false };
  try {
    return await _api(`/digest/${encodeURIComponent(campaignId)}/deliver`, { method: 'POST' });
  } catch (_) {
    return { ok: false };
  }
}

/**
 * Tell the engine the user is reading updates in the workspace now.
 * @param {boolean} present
 * @returns {Promise<object>}
 */
export async function setPresence(present = true) {
  try {
    const r = await fetch(`${API_BASE}/api/applicant/email/presence`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ present: !!present }),
    });
    if (!r.ok) return { ok: false };
    return { ok: true, present: !!present };
  } catch (_) {
    return { ok: false };
  }
}

/**
 * Approve a role straight from the digest view.
 * @param {string} applicationId
 * @returns {Promise<object>}
 */
export async function approveApplication(applicationId) {
  if (!applicationId) throw new Error('applicationId is required');
  return _api(`/applications/${encodeURIComponent(applicationId)}/approve`, { method: 'POST' });
}

/**
 * Decline a role with feedback (feeds learning).
 * @param {string} applicationId
 * @param {string} feedbackText
 * @param {object} criteriaDelta
 * @returns {Promise<object>}
 */
export async function declineApplication(applicationId, feedbackText = '', criteriaDelta = {}) {
  if (!applicationId) throw new Error('applicationId is required');
  return _api(`/applications/${encodeURIComponent(applicationId)}/decline`, {
    method: 'POST',
    body: { feedback_text: feedbackText, criteria_delta: criteriaDelta },
  });
}

/**
 * Send free-text feedback for a campaign.
 * @param {string} campaignId
 * @param {string} text
 * @param {object} criteriaDelta
 * @returns {Promise<object>}
 */
export async function sendFeedback(campaignId, text, criteriaDelta = {}) {
  if (!campaignId) throw new Error('campaignId is required');
  return _api('/feedback/freetext', {
    method: 'POST',
    body: { campaign_id: campaignId, text, criteria_delta: criteriaDelta },
  });
}

/**
 * Submit guided-survey feedback for a campaign.
 * @param {string} campaignId
 * @param {object} answers - {question_key: choice_value} map.
 * @returns {Promise<object>}
 */
export async function sendSurvey(campaignId, answers = {}) {
  if (!campaignId) throw new Error('campaignId is required');
  return _api('/feedback/survey', {
    method: 'POST',
    body: { campaign_id: campaignId, answers },
  });
}
