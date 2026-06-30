// static/js/applicantResearch.js
//
// JS consumer for the /api/applicant/research/* proxy routes.
//
// The engine exposes a manual deep-research trigger (capped/deduped/cached) that
// the autonomous agent also auto-escalates to on knowledge gaps. This module is
// the explicit user-initiated counterpart: it provides functions to trigger a
// research run and read the campaign's research budget.
//
// All functions degrade gracefully (never throw), returning a well-shaped
// degraded payload on failure so the caller always gets something renderable.

import { _fetchJSON, _post } from './applicantCore.js';

const API_BASE = window.location.origin;

/**
 * Run (or reuse) deep research for a campaign.
 * Returns the structured report from the engine:
 *   { summary, key_findings: [...], sources: [...], budget_remaining, ... }
 * When the research channel is off or budget exhausted the engine still returns
 * 200 with { unavailable: true, reason: "..." } — a degraded state, not an error.
 *
 * @param {string} campaignId
 * @param {object} opts
 * @param {string} opts.query - The research query (required).
 * @param {string} [opts.company] - Company name context.
 * @param {string} [opts.role] - Role title context.
 * @param {string} [opts.context] - Additional context.
 * @param {number} [opts.max_time] - Max research time in seconds.
 * @param {boolean} [opts.force] - Re-run even when a cached report exists.
 * @returns {Promise<object>}
 */
export async function runResearch(campaignId, opts = {}) {
  try {
    const body = {
      query: opts.query || '',
      company: opts.company || null,
      role: opts.role || null,
      context: opts.context || null,
      max_time: opts.max_time || null,
      force: !!opts.force,
    };
    return await _post(`/api/applicant/research/${encodeURIComponent(campaignId)}/run`, body);
  } catch (e) {
    return {
      unavailable: true,
      reason: e.message || 'Research is not available right now.',
      summary: '',
      key_findings: [],
      sources: [],
    };
  }
}

/**
 * Read the campaign's research budget + channel availability.
 * Returns:
 *   { engine_available: bool, campaign_id, available: bool,
 *     calls_made: number, budget_remaining: number }
 *
 * @param {string} campaignId
 * @returns {Promise<object>}
 */
export async function researchBudget(campaignId) {
  try {
    return await _fetchJSON(`/api/applicant/research/${encodeURIComponent(campaignId)}/budget`);
  } catch (_) {
    return {
      engine_available: false,
      campaign_id: campaignId,
      available: false,
      calls_made: 0,
      budget_remaining: 0,
    };
  }
}
