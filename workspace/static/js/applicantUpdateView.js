// static/js/applicantUpdateView.js
//
// Pure view helpers for the Update modal (applicantUpdate.js). Deliberately a
// dependency-free leaf module (no DOM, no fetch, no ./ui.js import) so it can be
// unit-tested under plain node and reused without dragging in the browser-only
// module graph. applicantUpdate.js imports + re-exports these.

// Map a defensively-consumed status payload to the plain-language view the modal
// renders. `state` may be absent if the engine/updater is down, so this never
// trusts a field to be present.
//   • running              → spinner-y headline, "Update now" disabled
//   • success / failed      → terminal headline + toast cue
//   • idle (or unknown)     → ready-to-update headline
// `engineAvailable === false` short-circuits to the offline view; an available
// engine whose `updater_available` is false yields a plain note (no dead button).
export function updateStateView(status) {
  const s = status || {};
  if (s.engine_available === false) {
    return {
      kind: 'offline',
      running: false,
      canTrigger: false,
      headline: 'Updates are unavailable right now',
      message: "I can't check for updates right now — Applicant isn't fully connected yet. This page will work once it is.",
    };
  }
  const state = typeof s.state === 'string' ? s.state : 'idle';
  const running = state === 'running';
  // The one-click updater isn't deployed on this install: don't offer a dead
  // button — tell the user to update once the normal way to enable it.
  if (s.updater_available === false) {
    return {
      kind: 'no-updater',
      running: false,
      canTrigger: false,
      headline: 'One-click updates not enabled yet',
      message: s.message
        || "One-click updates aren't set up here yet. Update once using the same method you first installed with, and the button will appear here afterwards.",
    };
  }
  if (running) {
    return {
      kind: 'running',
      running: true,
      canTrigger: false,
      headline: 'Updating…',
      message: s.message || 'Backing up your data, applying the latest version, and restarting. You can leave this open.',
    };
  }
  if (state === 'success') {
    return {
      kind: 'success',
      running: false,
      canTrigger: true,
      headline: 'Update complete',
      message: s.message || 'Applicant is up to date.',
    };
  }
  if (state === 'failed') {
    return {
      kind: 'failed',
      running: false,
      canTrigger: true,
      headline: "Update didn't finish",
      message: s.message || 'Something went wrong during the update. Your data was backed up first. You can try again.',
    };
  }
  // idle / unknown: ready to check + install.
  return {
    kind: 'idle',
    running: false,
    canTrigger: true,
    headline: 'Update Applicant',
    message: s.message
      || 'Runs the safe one-click update: backs up your data, applies the latest version, and restarts. No command line needed.',
  };
}

// Render a log_tail array (or anything) into a clean monospace string. Each entry
// is coerced to a single trimmed line; objects are JSON-stringified. Returns ''
// for an empty/absent tail so the caller can hide the block.
export function formatLogTail(tail) {
  if (!Array.isArray(tail) || !tail.length) return '';
  return tail
    .map((line) => (typeof line === 'string' ? line : JSON.stringify(line)))
    .map((line) => String(line).replace(/\s+$/, ''))
    .join('\n');
}
