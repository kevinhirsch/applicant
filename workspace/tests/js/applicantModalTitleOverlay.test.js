// workspace/tests/js/applicantModalTitleOverlay.test.js
//
// B12 (docs/APPLICANT-BACKLOG.md) — same contract as applicantModalTitle.test.js
// (see that file's header for the full rationale), ported to the path that
// ACTUALLY SHIPS. docker/Dockerfile.a0 builds the a0 web image FROM the pinned
// upstream `agent0ai/agent-zero` base image and layers on only two things:
// `COPY a0-applicant/ /a0/plugins/applicant/` (the plugin) and the a0-webui/
// overlay (`scripts/apply-branding.sh` copies a0-webui/ onto /a0/webui/ at
// build time). The vendored `agent-zero/webui/` subtree in this monorepo is a
// DEAD reference copy that ships nowhere — so the B12 fix landing only in
// `agent-zero/webui/js/modals.js` never reached a deployed instance.
//
// This test targets the file the build actually copies onto /a0/webui/js/
// modals.js: `a0-webui/js/modals.js`. It is currently a straight copy of the
// fixed dead-tree file (see tests/unit/test_ui_fork_overlay.py::
// TestModalTitleOverlay for the Python-side parity check), so the same
// assertions as applicantModalTitle.test.js apply here — reverting the fix on
// the DEPLOYABLE path (even if the dead copy stays fixed) makes this file go
// red, which is the whole point: it is the one that mirrors what ships.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const MODALS_PATH = fileURLToPath(
  new URL('../../../a0-webui/js/modals.js', import.meta.url),
);
const MODALS_SRC = readFileSync(MODALS_PATH, 'utf8');

// ── tiny source-slicer (brace-balanced, not a naive regex) ────────────────

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx}`);
}

function extractFunction(src, name, path) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in ${path}`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

function buildFriendlyTitleFromPath() {
  const code = [
    extractFunction(MODALS_SRC, 'friendlyTitleFromPath', 'a0-webui/js/modals.js'),
    'return friendlyTitleFromPath;',
  ].join('\n');
  return new Function(code)();
}

// ── the fallback the header actually renders on the DEPLOYED image ────────

test('the deployable overlay (a0-webui/js/modals.js) exists and is not the pristine upstream file', () => {
  assert.ok(MODALS_SRC.length > 0, 'a0-webui/js/modals.js must exist and be non-empty');
});

test('a0-webui/js/modals.js wires the header fallback through friendlyTitleFromPath, never the raw path', () => {
  assert.ok(
    MODALS_SRC.includes('doc.title || friendlyTitleFromPath(modalPath)'),
    'the modal-title assignment must derive a friendly name from the path, not dump modalPath verbatim',
  );
  // B12 regression guard: the old bug was `doc.title || modalPath` directly.
  assert.ok(
    !MODALS_SRC.includes('doc.title || modalPath;'),
    'must not have regressed back to dumping the raw modalPath as the title',
  );
});

test('friendlyTitleFromPath turns a plugin panel path into a clean title', () => {
  const friendlyTitleFromPath = buildFriendlyTitleFromPath();
  assert.equal(
    friendlyTitleFromPath('/plugins/applicant/webui/digest.html'),
    'Digest',
  );
});

test('friendlyTitleFromPath title-cases multi-word / underscored file names', () => {
  const friendlyTitleFromPath = buildFriendlyTitleFromPath();
  assert.equal(
    friendlyTitleFromPath('/plugins/applicant/webui/model_endpoints.html'),
    'Model Endpoints',
  );
  assert.equal(
    friendlyTitleFromPath('/plugins/applicant/webui/model-config.html'),
    'Model Config',
  );
});

test('friendlyTitleFromPath strips query strings and hashes before deriving the title', () => {
  const friendlyTitleFromPath = buildFriendlyTitleFromPath();
  assert.equal(
    friendlyTitleFromPath(
      '/plugins/applicant/webui/documents.html?application_id=abc123',
    ),
    'Documents',
  );
  assert.equal(
    friendlyTitleFromPath('/plugins/applicant/webui/audit.html#section-2'),
    'Audit',
  );
});

test('friendlyTitleFromPath never returns a bare filesystem path for a real component', () => {
  const friendlyTitleFromPath = buildFriendlyTitleFromPath();
  const examples = [
    '/plugins/applicant/webui/digest.html',
    '/plugins/applicant/webui/documents.html?application_id=xyz',
    '/plugins/applicant/webui/easy_apply.html',
  ];
  for (const p of examples) {
    const title = friendlyTitleFromPath(p);
    assert.ok(!title.includes('/'), `title for ${p} must not contain a path separator: got ${title}`);
    assert.ok(!title.endsWith('.html'), `title for ${p} must not carry the file extension: got ${title}`);
  }
});

test('friendlyTitleFromPath degrades to the original value for a blank/rootless path', () => {
  const friendlyTitleFromPath = buildFriendlyTitleFromPath();
  assert.equal(friendlyTitleFromPath(''), '');
  assert.equal(friendlyTitleFromPath(null), null);
});
