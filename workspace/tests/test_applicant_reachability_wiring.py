"""Regression coverage for the dark-engine audit's B1 findings 1 and 2:

  1. ``static/js/applicantReachability.js`` used to export three helpers that
     hit URLs with no backing route at all (a bare campaign-scoped
     ``ensure-submittable``, a nonexistent ``/api/applicant/criteria/{id}/
     learned``, and an unproxied ``/api/applicant/digest/deliver-now``) --
     every call 404'd, and nothing imported the module either. This file
     proves each corrected helper now hits the REAL, currently-wired proxy.
  2. The engine's ensure-submittable auto-heal
     (``src/applicant/app/routers/documents.py``) had no working caller --
     the only JS reference was the broken helper above. This file proves a
     one-click "Fix documents" control now exists on both the review surface
     (``documentLibrary.js``) and the Portal's blocked-material row
     (``applicantPortal.js``), wired to the corrected ``ensureSubmittable``
     helper.

The helper functions are pure (``fetch`` in, promise out) so the JS-contract
half runs the REAL ``applicantReachability.js`` under Node against a minimal
fetch mock -- no DOM needed, only its one transitive import (``ui.js``, via
``applicantCore.js``) is stubbed, the same technique used throughout this test
suite (see ``test_applicant_backlog_todaymode.py``'s ``_UI_STUB_LOADER``).

The button-wiring half is asserted at the source level (regex over the real
file, like ``test_applicant_promote_variant.py``'s ``_applicant_card_body``)
rather than full DOM execution, since both consumer modules are large,
closure-scoped surfaces not designed for import-and-drive testing.

Every assertion here was hand-verified to go RED against the pre-fix state
(the original three wrong URLs; no "Fix documents" button in either consumer)
before landing this file.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_REACHABILITY_JS = _JS_DIR / "applicantReachability.js"
_DOC_LIBRARY_JS = _JS_DIR / "documentLibrary.js"
_PORTAL_JS = _JS_DIR / "applicantPortal.js"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ══════════════════════════════════════════════════════════════════════════
# 1. applicantReachability.js: each helper hits the REAL proxy URL.
# ══════════════════════════════════════════════════════════════════════════

# applicantReachability.js -> applicantCore.js -> ui.js. Stub ui.js exactly like
# the Today/Portal JS-contract suites do -- these helpers never touch the DOM,
# only their _post/_fetchJSON plumbing (which reads `uiModule.esc`/`showToast`
# on error paths only) needs a fetch mock.
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'const uiModule = { showToast: function(){}, esc: function(s){ return s; } };' +
        'export default uiModule;'
      ),
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
`;
register('data:text/javascript,' + encodeURIComponent(__loaderSrc), import.meta.url);
"""

_FETCH_MOCK = """
globalThis.__fetchCalls = [];
globalThis.fetch = async (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  let body = null;
  try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch { body = opts && opts.body; }
  globalThis.__fetchCalls.push({ url: String(url), method, body });
  return { ok: true, status: 200, json: async () => ({}) };
};
"""


def _run_node(js_body: str) -> dict:
    script = "\n".join([_UI_STUB_LOADER, _FETCH_MOCK, js_body, "process.exit(0);"])
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=20,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError(f"node produced no stdout\nSTDERR:\n{res.stderr}")
    return json.loads(out_lines[-1])


def test_ensure_submittable_posts_to_the_per_application_endpoint(node_available):
    script = f"""
        const mod = await import('file://{_REACHABILITY_JS}');
        await mod.ensureSubmittable('app-7');
        const call = globalThis.__fetchCalls[0];
        console.log(JSON.stringify({{ url: call.url, method: call.method }}));
    """
    out = _run_node(script)
    assert out == {
        "url": "/api/applicant/documents/applications/app-7/ensure-submittable",
        "method": "POST",
    }


def test_fetch_learned_criteria_reads_the_memory_criteria_endpoint(node_available):
    script = f"""
        const mod = await import('file://{_REACHABILITY_JS}');
        await mod.fetchLearnedCriteria('camp-3');
        const call = globalThis.__fetchCalls[0];
        console.log(JSON.stringify({{ url: call.url, method: call.method }}));
    """
    out = _run_node(script)
    assert out == {
        "url": "/api/applicant/memory/criteria?campaign_id=camp-3",
        "method": "GET",
    }


def test_deliver_digest_now_posts_to_the_live_campaign_scoped_endpoint(node_available):
    script = f"""
        const mod = await import('file://{_REACHABILITY_JS}');
        await mod.deliverDigestNow('camp-9');
        const call = globalThis.__fetchCalls[0];
        console.log(JSON.stringify({{ url: call.url, method: call.method }}));
    """
    out = _run_node(script)
    assert out == {
        "url": "/api/applicant/email/campaigns/camp-9/digest/deliver",
        "method": "POST",
    }


# ══════════════════════════════════════════════════════════════════════════
# 2. "Fix documents" wiring: documentLibrary.js review cards.
# ══════════════════════════════════════════════════════════════════════════


def test_document_library_imports_the_corrected_ensure_submittable_helper():
    src = _read(_DOC_LIBRARY_JS)
    assert "import { ensureSubmittable } from './applicantReachability.js';" in src


def test_document_library_renders_a_fix_documents_button_when_review_is_needed():
    src = _read(_DOC_LIBRARY_JS)
    assert "doclib-applicant-fix-documents" in src
    assert "Fix documents" in src
    # Reuses the existing design-system button class, no hand-rolled style.
    assert re.search(r'class="cal-btn doclib-applicant-fix-documents"', src)


def test_document_library_fix_documents_button_calls_ensure_submittable_and_refreshes():
    src = _read(_DOC_LIBRARY_JS)
    handler = src[src.index("const fixBtn = head.querySelector"):]
    handler = handler[: handler.index("\n      }\n") + len("\n      }\n")]
    assert "await ensureSubmittable(appId);" in handler
    assert "_loadApplicantMaterials(appId, results)" in handler
    assert "uiModule.showToast(" in handler


# ══════════════════════════════════════════════════════════════════════════
# 3. "Fix documents" wiring: the Portal's blocked-material row.
# ══════════════════════════════════════════════════════════════════════════


def test_portal_imports_the_corrected_ensure_submittable_helper():
    src = _read(_PORTAL_JS)
    assert "import { ensureSubmittable } from './applicantReachability.js';" in src


def _render_review_body() -> str:
    src = _read(_PORTAL_JS)
    fn = re.search(r"function _renderReview\(item\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected the _renderReview(item) renderer"
    return fn.group(0)


def test_portal_review_row_renders_a_fix_documents_button():
    body = _render_review_body()
    assert "applicant-portal-fix-documents" in body
    assert "Fix documents" in body


def test_portal_fix_documents_button_is_wired_to_ensure_submittable():
    src = _read(_PORTAL_JS)
    wiring = re.search(
        r"host\.querySelectorAll\('\.applicant-portal-fix-documents'\).*?\n  \}\);\n",
        src,
        re.S,
    )
    assert wiring, "expected a click handler wired for .applicant-portal-fix-documents"
    block = wiring.group(0)
    assert "await ensureSubmittable(appId);" in block
    assert "_toast(" in block
