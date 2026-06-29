// static/js/applicantReachability.js
//
// Reachability wiring: ensure-submittable, learned criteria, digest deliver-now.
// Import this module wherever applicant-side reachability actions are needed.

import { _fetchJSON, _post } from './applicantCore.js';

/** POST to ensure-submittable for the given campaign. */
export function ensureSubmittable(campaignId) {
  return _post('/api/applicant/documents/ensure-submittable', { campaign_id: campaignId });
}

/** GET learned criteria for the given campaign. */
export function fetchLearnedCriteria(campaignId) {
  return _fetchJSON(`/api/applicant/criteria/${campaignId}/learned`);
}

/** POST to deliver digest immediately for the given campaign. */
export function deliverDigestNow(campaignId) {
  return _post('/api/applicant/digest/deliver-now', { campaign_id: campaignId });
}
