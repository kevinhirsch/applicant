"""P1-13 — the "facts to double-check" surface in the document review UI.

The balanced truth policy lets the assistant rewrite a draft freely and SURFACES
any fact-class specifics (skills / employers / credentials / dates / numbers) that
aren't in the profile yet, rather than blocking them — nothing is sent until the
human approves. The remaining FE work (issue #665) wires that surfacing through the
whole chain: engine flagged-facts read -> workspace proxy -> the review panel in
``documentLibrary.js``, with one-tap "yes, that's true — add to my profile" (which
persists through the SAME confirm-conflict endpoint onboarding's Q&A-conflicts flow
uses) and "Remove" (a subtract turn).

These are source-composition assertions (no browser / DOM), mirroring the existing
``test_applicant_documentlibrary_redline_lens04`` review-panel tests: they hand-verify
the wiring is present so a later refactor that quietly drops it fails loudly.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCLIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"
DOCS_ROUTES = REPO_ROOT / "workspace" / "routes" / "applicant_documents_routes.py"
ENGINE_CLIENT = REPO_ROOT / "workspace" / "src" / "applicant_engine.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── JS: the review panel loads + renders the flagged facts ─────────────────

def test_review_render_loads_flagged_facts():
    """`_renderApplicantReview` must kick off the flagged-facts fetch so the
    "facts to double-check" panel appears in the open review, alongside the
    redline it already renders."""
    js = _read(DOCLIB_JS)
    assert "_loadApplicantFlaggedFacts(item, appId, flaggedSlot, panel, card, results)" in js, (
        "expected the review render to load flagged facts into a slot"
    )
    assert "function _loadApplicantFlaggedFacts(" in js
    assert "function _renderApplicantFlaggedFacts(" in js


def test_flagged_facts_fetches_the_proxy_read():
    """The panel reads the workspace proxy's per-document flagged-facts endpoint."""
    js = _read(DOCLIB_JS)
    assert "/flagged-facts`" in js, "expected a fetch of the flagged-facts proxy read"


def test_flagged_facts_clean_or_error_renders_nothing():
    """A clean draft (no flagged facts) or a failed read renders nothing — the
    absence of facts must never be dressed up as a check, and a best-effort read
    must never block the review card below it."""
    js = _read(DOCLIB_JS)
    assert "if (!flagged.length) return;" in js, (
        "expected an empty flagged list to render nothing"
    )


def test_add_to_profile_uses_confirm_conflict_endpoint():
    """The one-tap "yes, that's true — add to my profile" persists through the
    SAME confirm-conflict endpoint onboarding's Q&A-conflicts flow uses (issue
    #665 ties the two together), so a confirmed fact stops being flagged and can
    be reused."""
    js = _read(DOCLIB_JS)
    assert "add to my profile" in js, "expected the confirm affordance label"
    assert "/api/applicant/setup/onboarding/${encodeURIComponent(campaignId)}/confirm-conflict" in js, (
        "expected 'add to my profile' to POST the confirm-conflict endpoint"
    )


def test_remove_uses_a_subtract_turn():
    """"Remove" takes the fact out of the draft through the existing review turn
    loop (kind:'subtract') rather than a bespoke path."""
    js = _read(DOCLIB_JS)
    assert "kind: 'subtract', instruction: fact" in js, (
        "expected Remove to drive a subtract turn on the existing turn endpoint"
    )


def test_flagged_fact_label_is_textcontent_not_innerhtml():
    """Model-derived fact tokens reach the panel; they must be set via textContent
    so they can never inject markup."""
    js = _read(DOCLIB_JS)
    assert "label.textContent = fact;" in js, (
        "expected the flagged fact token to be rendered as textContent"
    )


# ── proxy + engine client: the read is wired ───────────────────────────────

def test_proxy_exposes_flagged_facts_read():
    py = _read(DOCS_ROUTES)
    assert '@router.get("/{document_id}/flagged-facts")' in py
    assert "engine.document_flagged_facts(document_id)" in py


def test_flagged_facts_read_is_owner_gated_disc15():
    """Flagged facts are the owner's profile gaps / draft personal facts on the
    single-tenant engine — the read must use require_engine_owner, not plain
    require_user (a second workspace account must never see them)."""
    py = _read(DOCS_ROUTES)
    body = py.split('@router.get("/{document_id}/flagged-facts")')[1]
    body = body.split("@router.get", 1)[0]
    assert "require_engine_owner(request)" in body
    assert "require_user(request)" not in body


def test_engine_client_has_flagged_facts_method():
    py = _read(ENGINE_CLIENT)
    assert "async def document_flagged_facts(self, document_id: str)" in py
    assert "/api/documents/{document_id}/flagged-facts" in py
