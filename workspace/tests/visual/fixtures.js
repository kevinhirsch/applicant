// workspace/tests/visual/fixtures.js
//
// Deterministic response fixtures for the P0-3 gadget-rail states. The rail
// is a lens over live owner data (portal/tracker/activity/guardrails/results/
// health/digest proxies) and hides gadgets whose backing is offline/empty —
// so with no engine the rail renders bare. These fixtures stand in for the
// engine's demo/dev_seed dataset (which needs a live Postgres engine this
// hermetic harness does not boot) with FIXED payloads shaped exactly like the
// proxies' real responses, so the pinned / collapsed / notifications-expanded
// rail states actually show the gadget stack, badge strip and waiting queue.
// Content is synthetic and clearly fictional — never a real employer pipeline.

'use strict';

const RAIL_FIXTURES = [
  {
    pattern: '**/api/applicant/portal/pending/count',
    body: { engine_available: true, count: 3 },
  },
  {
    pattern: '**/api/applicant/portal/pending',
    body: {
      engine_available: true,
      count: 3,
      items: [
        { title: 'Review the tailored resume for Maple & Co' },
        { title: 'Approve the cover letter for Northwind Labs' },
        { title: 'A screening question needs your answer — Cedar Analytics' },
      ],
    },
  },
  {
    pattern: '**/api/applicant/tracker',
    body: {
      engine_available: true,
      has_data: true,
      applications: [
        { stage: 'interview' }, { stage: 'submitted' }, { stage: 'submitted' },
        { stage: 'offer' }, { stage: 'active' }, { stage: 'active' },
      ],
    },
  },
  {
    pattern: '**/api/applicant/activity/runs*',
    body: {
      engine_available: true,
      items: [
        { intent: 'Searched three boards for new matches' },
        { intent: 'Tailored a resume draft for your review' },
        { intent: 'Queued two applications for your approval' },
      ],
    },
  },
  {
    pattern: '**/api/applicant/campaigns',
    body: { campaigns: [{ id: 'demo-campaign', name: 'Product roles' }] },
  },
  {
    pattern: '**/api/applicant/campaigns/demo-campaign/guardrails',
    body: {
      today: {
        applications_today: 4,
        daily_target: 10,
        hard_cap: 15,
        usage_reported: true,
        cost_today_usd_estimate: 1.23,
      },
    },
  },
  {
    pattern: '**/api/applicant/email/digest/demo-campaign',
    body: { engine_available: true, roles: [{}, {}, {}] },
  },
  {
    pattern: '**/api/applicant/results',
    body: {
      engine_available: true,
      has_data: true,
      summary: { total_submitted: 12, total_approved: 9, total_matched: 31 },
    },
  },
  {
    pattern: '**/api/applicant/health/capabilities',
    body: {
      engine_available: true,
      all_real: true,
      capabilities: [
        { id: 'discovery' }, { id: 'tailoring' }, { id: 'prefill' },
        { id: 'digest' }, { id: 'notifications' },
      ],
      degraded: [],
    },
  },
];

/**
 * Unlock fixture for the nav-section states: with no engine, the feature
 * layer honestly HIDES the gated sections (P0-4: absence over padlocks), so
 * their surfaces would be unreachable in this hermetic walk. This fixture
 * rewrites the REAL `/api/applicant/features` payload (section keys/nav_ids
 * stay exactly what applicant_features.py computes) marking every section
 * `active` — the nav renders, each surface opens, and its INNER content
 * still shows the honest engine-offline / empty-state rendering, which is
 * the baseline being pinned. Sections marked present_but_disabled stay
 * disabled (not in this build = not in the matrix).
 */
async function installUnlockFixture(page) {
  await page.route('**/api/applicant/features', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const resp = await route.fetch();
    let json;
    try { json = await resp.json(); } catch (_) { return route.fulfill({ response: resp }); }
    json.engine_available = true;
    const sections = json.sections || {};
    for (const key of Object.keys(sections)) {
      if (!sections[key].present_but_disabled) sections[key].state = 'active';
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(json),
    });
  });
}

/** Install the rail fixtures on a page (GET-only; everything else passes through). */
async function installRailFixtures(page) {
  for (const fx of RAIL_FIXTURES) {
    await page.route(fx.pattern, (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fx.body),
      });
    });
  }
}

module.exports = { RAIL_FIXTURES, installRailFixtures, installUnlockFixture };
