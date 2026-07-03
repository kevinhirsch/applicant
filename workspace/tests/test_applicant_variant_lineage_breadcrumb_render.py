"""Regression coverage for rendering the résumé-variant ancestry breadcrumb
(dark-engine audit item 50).

Background (verified by reading the code, not assumed):

* ``MaterialService.lineage(variant)`` (``src/applicant/application/services/
  material_service.py``) already walks a résumé variant's ``parent_id`` chain to
  the root. Before this change nothing called it from the routed variant
  library, and the front door only showed a raw ``lineage_depth`` count plus an
  unreadable ``parent_id`` UUID (e.g. "3 edits deep - from 7c1e...").
* The engine route (``src/applicant/app/routers/documents.py`` ``list_variants``)
  now attaches a ``lineage`` list to each variant row: root-first, each entry
  ``{variant_id, is_root, targeted_jd_signature, approved}``, ending with the
  variant itself.
* The workspace proxy (``routes/applicant_documents_routes.py`` ``variant_library``)
  hands the engine's JSON back UNCHANGED — a bare
  ``ApplicantEngineClient.list_variants`` passthrough with no field stripping
  (confirmed by reading the route; covered separately by
  ``test_applicant_variant_lineage_breadcrumb.py``), so no proxy change was
  needed for this task.

This module confines itself to ``workspace/static/js/documentLibrary.js``, the
only front-end file this task touches. Follows the
``test_applicant_variant_fitscore_display.py`` convention: source-text regex
assertions against the browser-only module (no DOM-independent entry point
cheap enough to shim). Each assertion here was hand-verified to go RED when
the corresponding piece of the change is reverted (temporarily restored the
pre-fix source via a file-copy backup, reran and saw a real AssertionError,
then restored the fix and reran green — NOT git stash, per the shared-worktree
constraint on this task).
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_LIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"


def _read() -> str:
    return DOC_LIB_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n    \}}", src, re.S)
    assert m, f"expected a function {name}(...) in the source"
    return m.group(1)


def _async_top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"async function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n    \}}", src, re.S)
    assert m, f"expected an async function {name}(...) in the source"
    return m.group(1)


# ── the shared breadcrumb formatter ─────────────────────────────────────────


def test_lineage_breadcrumb_helper_exists():
    src = _read()
    assert re.search(r"function _applicantLineageBreadcrumb\(lineage, esc\)\s*\{", src), (
        "expected a top-level _applicantLineageBreadcrumb(lineage, esc) helper — "
        "reverting this removes the function entirely and this regex goes red"
    )


def test_lineage_breadcrumb_hides_gracefully_for_a_lone_root_variant():
    """A variant with no ancestors (a one-entry lineage: just itself) has
    nothing to trace — must render nothing, not a one-word breadcrumb."""
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    assert "chain.length < 2" in body and "return ''" in body


def test_lineage_breadcrumb_labels_the_root_as_original():
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    assert "node && node.is_root" in body
    assert "'Original'" in body


def test_lineage_breadcrumb_labels_the_current_variant_as_this_version():
    """Matches the audit item's own example: "Original -> Tailored for Acme ->
    this version" — the LAST entry (the variant itself) reads as "this
    version", not its raw id."""
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    assert re.search(r"idx === chain\.length - 1", body)
    assert "'this version'" in body


def test_lineage_breadcrumb_names_intermediate_ancestors_by_their_target():
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    assert "node.targeted_jd_signature" in body
    assert "Tailored for" in body


def test_lineage_breadcrumb_escapes_each_label_before_joining():
    """Labels are user/JD-derived text (targeted_jd_signature) — must go
    through the caller-supplied esc() before landing in the joined string."""
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    assert "labels.map(esc)" in body


def test_lineage_breadcrumb_is_white_label_plain_language():
    """No internal jargon (FR-/NFR- ids, raw wire field names) leaking into
    the user-visible label strings themselves."""
    body = _top_level_fn(_read(), "_applicantLineageBreadcrumb")
    label_lines = [ln for ln in body.splitlines() if "return" in ln or "'Original'" in ln or "'this version'" in ln]
    joined = "\n".join(label_lines)
    assert "FR-" not in joined and "NFR-" not in joined
    assert "lineage_depth" not in joined


# ── wired into the campaign-scoped resume-variant library ──────────────────


def test_variant_library_computes_the_breadcrumb_from_the_real_lineage_field():
    """`_loadVariantLibrary` (the campaign-scoped "Resume variants" panel,
    wired to the doclib-variant-lookup-btn) must read the engine's real
    per-variant `lineage` array, not fabricate one."""
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert "_applicantLineageBreadcrumb(v.lineage, esc)" in body


def test_variant_library_still_renders_the_pre_existing_depth_and_parent_fields():
    """Additive, not a replacement: the existing lineage_depth/parent_id
    summary this task's own instructions say is unreadable stays in place
    alongside the new breadcrumb (reverting only the breadcrumb hunk must
    leave these untouched)."""
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert "v.lineage_depth" in body
    assert "v.parent_id" in body


def test_variant_library_breadcrumb_is_gated_on_hidden_when_empty():
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    m = re.search(
        r"const breadcrumb = _applicantLineageBreadcrumb\(v\.lineage, esc\);\s*\n"
        r"\s*const breadcrumbHtml = breadcrumb\s*\n\s*\?",
        body,
    )
    assert m, "expected the breadcrumb HTML to be built only when breadcrumb is non-empty"


def test_variant_library_breadcrumb_html_is_appended_to_the_card():
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert "breadcrumbHtml +" in body


# ── node syntax sanity (mirrors every other documentLibrary.js test file) ──


def test_document_library_js_is_syntactically_valid(node_available):
    import subprocess

    result = subprocess.run(
        ["node", "--check", str(DOC_LIB_JS)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def node_available():
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")
