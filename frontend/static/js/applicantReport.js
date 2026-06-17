// Applicant failure ring, browser side (Lane G11) — the standard sink for fail-open catches.
//
// The house style for user-facing feature failure is fail-OPEN: the panel simply isn't
// there, the chip doesn't render, the portrait stays a placeholder. Correct UX —
// structurally SILENT: every failure renders as absence, and nobody learns anything
// (the image-gen complaint, generalized). This module fixes the silence WITHOUT
// changing the UX: a fail-open catch adds ONE line — ApplicantReport.fail(surface,
// errorClass, detail) — and the failure lands in the G1b LIVE ring (POST
// /api/applicant/fe-report → logger.info("[fe-fail] …")), visible on /admin/status.
//
// Contract: throttled client-side (max ~10/min), rate-limited server-side, and it
// NEVER throws — reporting a failure must never become one. Loaded as a plain
// script BEFORE the applicant panels, so window.ApplicantReport exists when they run;
// call sites still guard (`window.ApplicantReport && …`) in case this file 404s.
(function () {
  "use strict";

  const ENDPOINT = "/api/applicant/fe-report";
  const MAX_PER_MIN = 10; // client-side throttle; the route enforces its own on top
  let stamps = [];        // send timestamps inside the sliding minute

  function clip(v, n) {
    try { return String(v == null ? "" : v).slice(0, n); } catch (_) { return ""; }
  }

  function fail(surface, errorClass, detail) {
    try {
      const now = Date.now();
      stamps = stamps.filter((t) => now - t < 60000);
      if (stamps.length >= MAX_PER_MIN) return;
      stamps.push(now);
      const body = JSON.stringify({
        surface: clip(surface, 80),
        errorClass: clip(errorClass, 120),
        detail: clip(detail, 300),
      });
      let sent = false;
      try {
        // sendBeacon survives page unload; a Blob carries the JSON content type.
        if (navigator.sendBeacon) sent = navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
      } catch (_) { sent = false; }
      if (!sent) {
        fetch(ENDPOINT, {
          method: "POST", credentials: "same-origin", keepalive: true,
          headers: { "Content-Type": "application/json" }, body,
        }).catch(() => {});
      }
    } catch (_) { /* never throws — the report is an addition, never new behavior */ }
  }

  window.ApplicantReport = { fail };
})();
