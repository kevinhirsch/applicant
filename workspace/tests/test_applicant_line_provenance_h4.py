"""H4 — visible provenance: the "Where this came from" surface in document review.

The review screen traces each generated line to the owner's real history: the
engine's per-line provenance read (same fabrication-guard matchers as the
flagged-facts read) flows engine -> workspace proxy -> a per-line panel in
``documentLibrary.js`` that names WHICH source (a profile attribute, the base
résumé, the posting being addressed) supports each fact-class token — and marks
unsourced tokens instead of hiding them. A check that could not run renders an
honest "couldn't check" note, never nothing (the H-series rule: the absence of a
check must never read as a clean check).

These are source-composition assertions (no browser / DOM), mirroring
``test_applicant_flagged_facts_p1_13.py``: they hand-verify the wiring so a later
refactor that quietly drops it fails loudly.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCLIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"
DOCS_ROUTES = REPO_ROOT / "workspace" / "routes" / "applicant_documents_routes.py"
ENGINE_CLIENT = REPO_ROOT / "workspace" / "src" / "applicant_engine.py"
ENGINE_ROUTER = REPO_ROOT / "src" / "applicant" / "app" / "routers" / "documents.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── JS: the review panel loads + renders the per-line provenance ────────────

def test_review_render_loads_line_provenance():
    """`_renderApplicantReview` must kick off the provenance fetch so the
    "Where this came from" panel appears in the open review, alongside the
    research-provenance and flagged-facts panels it already renders."""
    js = _read(DOCLIB_JS)
    assert "_loadApplicantLineProvenance(item, provenanceSlot)" in js, (
        "expected the review render to load line provenance into a slot"
    )
    assert "function _loadApplicantLineProvenance(" in js
    assert "function _renderApplicantLineProvenance(" in js


def test_line_provenance_fetches_the_proxy_read():
    """The panel reads the workspace proxy's per-document provenance endpoint."""
    js = _read(DOCLIB_JS)
    assert "/provenance`" in js, "expected a fetch of the provenance proxy read"


def test_failed_check_renders_honest_note_not_nothing():
    """H-series: a provenance check that could not run must render an explicit
    "couldn't check" note — never nothing, which would be indistinguishable
    from "all sourced"."""
    js = _read(DOCLIB_JS)
    assert "data.checked === false" in js
    assert "doclib-applicant-provenance-unchecked" in js
    assert js.count("I couldn't check where this draft's details came from just now.") >= 1


def test_unsourced_tokens_are_marked_not_hidden():
    """Tokens tracing to nothing render with an explicit caution marker (the
    same orange tone the flagged-facts panel uses) and copy pointing at the
    double-check panel — flagged, never silently dropped from the view."""
    js = _read(DOCLIB_JS)
    assert "not in your profile yet" in js
    assert "var(--orange, #ffb86c)" in js


def test_provenance_text_is_textcontent_not_innerhtml():
    """Line text, fact tokens and source labels are model/engine-derived; they
    must be set via textContent so they can never inject markup."""
    js = _read(DOCLIB_JS)
    body = js.split("function _renderApplicantLineProvenance(")[1].split("\n    }\n")[0]
    assert "innerHTML" not in body.replace("slot.innerHTML = ''", "")
    assert "chip.textContent" in body
    assert "lineEl.textContent" in body


# ── proxy + engine client + engine router: the read is wired ───────────────

def test_proxy_exposes_provenance_read():
    py = _read(DOCS_ROUTES)
    assert '@router.get("/{document_id}/provenance")' in py
    assert "engine.document_provenance(document_id)" in py


def test_provenance_read_is_owner_gated():
    """Provenance names the owner's profile attributes and résumé content on the
    single-tenant engine — the read must use require_engine_owner, not plain
    require_user (a second workspace account must never see it)."""
    py = _read(DOCS_ROUTES)
    body = py.split('@router.get("/{document_id}/provenance")')[1]
    body = body.split("@router.get", 1)[0]
    assert "require_engine_owner(request)" in body
    assert "require_user(request)" not in body


def test_proxy_engine_error_degrades_to_unchecked_with_reason():
    py = _read(DOCS_ROUTES)
    body = py.split('@router.get("/{document_id}/provenance")')[1]
    body = body.split("@router.get", 1)[0]
    assert '"checked": False' in body
    assert '"reason"' in body


def test_engine_client_has_provenance_method():
    py = _read(ENGINE_CLIENT)
    assert "async def document_provenance(self, document_id: str)" in py
    assert "/api/documents/{document_id}/provenance" in py


def test_engine_router_exposes_provenance_endpoint():
    py = _read(ENGINE_ROUTER)
    assert '@router.get("/{document_id}/provenance")' in py
    assert "line_provenance_for_document" in py
