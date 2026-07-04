// static/js/applicantReachability.js
//
// Reachability wiring: ensure-submittable, learned criteria, digest deliver-now.
// Import this module wherever applicant-side reachability actions are needed.
//
// dark-engine audit item 1: this module used to point at three URLs that do
// not exist on the workspace side (a bare campaign-scoped ensure-submittable,
// a `/api/applicant/criteria/{id}/learned` that has no router, and a
// `/api/applicant/digest/deliver-now` that was never proxied) -- every call
// 404'd, and nothing imported the module anyway, so the "reachability" file
// was itself unreachable. These now hit the real, currently-wired proxies:
//
//   * ensureSubmittable  -> the PER-APPLICATION proxy in
//     applicant_documents_routes.py (`POST /api/applicant/documents/
//     applications/{application_id}/ensure-submittable`) -- the engine route
//     takes an application id, not a campaign id.
//   * fetchLearnedCriteria -> the campaign's criteria read in
//     applicant_memory_routes.py (`GET /api/applicant/memory/criteria`),
//     which already includes any learned adjustment -- there is no separate
//     `/criteria/{id}/learned` router anywhere in the engine.
//   * deliverDigestNow -> the live "manual digest delivery" lane in
//     applicant_email_routes.py (`POST /api/applicant/email/campaigns/
//     {campaign_id}/digest/deliver`), the one `emailLibrary/applicantDigest.js`
//     already calls -- NOT the older, unused `/digest/{id}/deliver` route
//     removed alongside this fix (dark-engine audit item 5).

import { _fetchJSON, _post } from './applicantCore.js';

/**
 * POST to ensure-submittable for the given application (dark-engine audit
 * item 2). Enforces the review gate before submission; rejects with a 409
 * (surfaced on the thrown error's `.body.detail`) when some material is
 * still unapproved.
 */
export function ensureSubmittable(applicationId) {
  return _post(
    `/api/applicant/documents/applications/${encodeURIComponent(applicationId)}/ensure-submittable`,
    {},
  );
}

/** GET the campaign's search criteria, including any learned adjustment. */
export function fetchLearnedCriteria(campaignId) {
  return _fetchJSON(`/api/applicant/memory/criteria?campaign_id=${encodeURIComponent(campaignId)}`);
}

/** POST to deliver the digest immediately for the given campaign. */
export function deliverDigestNow(campaignId) {
  return _post(
    `/api/applicant/email/campaigns/${encodeURIComponent(campaignId)}/digest/deliver`,
    {},
  );
}
