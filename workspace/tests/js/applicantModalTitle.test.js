// workspace/tests/js/applicantModalTitle.test.js
//
// B12 (docs/APPLICANT-BACKLOG.md) — modal titles must never dump a raw
// filesystem/component path. ``agent-zero/webui/js/modals.js`` sets the modal
// header from ``doc.title || friendlyTitleFromPath(modalPath)`` — every
// Applicant panel fragment (digest.html, documents.html, model_endpoints.html,
// ...) has no ``<title>`` of its own, so the fallback is what every Applicant
// modal actually shows in practice. This pins the fallback: it must turn a
// component path into a clean human title, never the path itself.
//
// Like applicantEmptyStates.test.js, this does NOT import modals.js directly:
// the module touches browser globals (``document.createElement``,
// ``document.body.appendChild``) at top-level eval time, which throws under
// plain Node. Instead we read the REAL source and extract the exported
// ``friendlyTitleFromPath`` function via a balanced-brace slice, so reverting
// the fix in the source makes these assertions go red again.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const MODALS_PATH = fileURLToPath(
  new URL('../../../agent-zero/webui/js/modals.js', import.meta.url),
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
    extractFunction(MODALS_SRC, 'friendlyTitleFromPath', 'modals.js'),
    'return friendlyTitleFromPath;',
  ].join('\n');
  return new Function(code)();
}

// ── the fallback the header actually renders ───────────────────────────────

test('modals.js wires the header fallback through friendlyTitleFromPath, never the raw path', () => {
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
