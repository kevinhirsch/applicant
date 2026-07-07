"""Step bindings for the materials / résumé-rendering / documents acceptance specs.

Theme T07 — issues #170, #178, #187, #197, #246, #272, #273, #289, #293.

Follows the canonical enhancement-Gherkin pattern (see ``test_enh_research_steps``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual core rules / services /
  adapters and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real target (a
  speculative import, a missing attribute, an absent field, or an assertion the current
  code fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target core rules (``core/rules``), entities, and application
services through in-memory adapters — never UI internals, never real TeX/LibreOffice
binaries or network/DB. Speculative imports live INSIDE the step body so an absent
target raises at runtime (xfail) rather than breaking collection for the whole suite.
"""

from __future__ import annotations

import importlib

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.core.entities.generated_document import DocumentType
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.errors import TruthfulnessViolation
from applicant.core.ids import CampaignId, JobPostingId, ResumeVariantId, new_id
from applicant.core.rules.materials import (
    AGGRESSIVENESS_MAX,
    AGGRESSIVENESS_MIN,
    aggressiveness_directive,
    clamp_aggressiveness,
)

scenarios(
    "../features/enhancements/enh_170_phone_paren.feature",
    "../features/enhancements/enh_178_render_stub_path.feature",
    "../features/enhancements/enh_187_aggressiveness_dial.feature",
    "../features/enhancements/enh_197_attachment_types.feature",
    "../features/enhancements/enh_246_silent_failure_diagnostics.feature",
    "../features/enhancements/enh_272_slider_disabled_markup.feature",
    "../features/enhancements/enh_273_suggested_attribute_card.feature",
    "../features/enhancements/enh_289_doclib_cross_surface.feature",
    "../features/enhancements/enh_293_doclib_integration.feature",
)


@pytest.fixture
def t07ctx() -> dict:
    return {}


def _material_service(storage=None):
    """Build a MaterialService with no model wired (deterministic truthful path)."""
    from applicant.adapters.storage.in_memory import InMemoryStorage
    from applicant.application.services.material_service import MaterialService

    return MaterialService(storage or InMemoryStorage(), llm=None)


# ===========================================================================
# #170 — résumé parser: parenthesized work-history company (GREEN) + phone (PENDING)
# ===========================================================================
@given("a résumé whose experience line parenthesizes the date range")
def resume_paren_dates(t07ctx):
    t07ctx["resume_text"] = (
        "Jane Engineer\njane@example.com\n\n"
        "Experience\n"
        "Senior Engineer, Acme Corp (Jan 2020 - Present)\n"
    )


@given("a résumé whose contact line shows a parenthesized phone number")
def resume_paren_phone(t07ctx):
    t07ctx["resume_text"] = "Jane Engineer\n(555) 012-3456\njane@example.com\n"


@when("the résumé is parsed")
def parse_resume(t07ctx):
    import tempfile
    from pathlib import Path

    from applicant.adapters.resume_parser.resume_parser import ResumeParser

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "resume.txt"
        p.write_text(t07ctx["resume_text"], encoding="utf-8")
        t07ctx["parsed"] = ResumeParser().parse(str(p))


@then("the company name carries no leftover opening bracket")
def company_no_bracket(t07ctx):
    parsed = t07ctx["parsed"]
    assert parsed.work_history, "expected at least one work-history entry"
    company = parsed.work_history[0].company
    # The parser strips dangling brackets/separators off the company (FR-RESUME-3).
    assert "(" not in company and company.strip("( ").startswith("Acme")


@then("the parsed phone keeps the leading opening bracket")
def phone_keeps_bracket(t07ctx):
    # Today the phone regex starts at the first DIGIT, so "(555) 012-3456" parses as
    # "555) 012-3456" — the opening paren is dropped. Genuine red until the fix lands.
    phone = t07ctx["parsed"].phone
    assert phone.startswith("("), f"opening bracket dropped from phone: {phone!r}"


# ===========================================================================
# #178 — render path-selection: auto → stub when no binary (GREEN); real PDF (PENDING)
# ===========================================================================
@given("a LaTeX résumé adapter in auto render mode with no TeX engine available")
def latex_no_engine(t07ctx, monkeypatch):
    from applicant.adapters.resume_tailoring import latex_tailor

    # No TeX engine on PATH -> auto mode must NOT attempt a real compile.
    monkeypatch.setattr(latex_tailor.shutil, "which", lambda _name: None)
    t07ctx["latex"] = latex_tailor.LatexTailor(render_mode="auto")


@given("a LaTeX résumé adapter forced to render with no TeX engine available")
def latex_forced_no_engine(t07ctx, monkeypatch):
    from applicant.adapters.resume_tailoring import latex_tailor

    # render_mode="on" forces the real compile; with no engine on PATH the compile
    # produces no PDF, so the adapter must report an honest approximate-preview note.
    monkeypatch.setattr(latex_tailor.shutil, "which", lambda _name: None)
    t07ctx["latex"] = latex_tailor.LatexTailor(render_mode="on")


@when("a résumé artifact is rendered")
def render_latex_artifact(t07ctx):
    vid = ResumeVariantId(new_id())
    source = "\\section{Experience}\nSenior Engineer at Acme.\n"
    t07ctx["render"] = t07ctx["latex"].render_artifact(vid, source)


@then("the real compile is not attempted")
def real_compile_not_attempted(t07ctx):
    # auto + no engine => _allow_compile is False (no subprocess ever spawned), and the
    # deterministic estimate is returned rather than a real compile.
    assert t07ctx["latex"]._allow_compile is False


@then("the result is flagged as an approximate preview rather than a faithful match")
def render_flagged_preview(t07ctx):
    render = t07ctx["render"]
    assert render.fidelity_ok is False
    assert "approximate preview" in render.notes.lower()


@given("a docx résumé adapter in auto render mode with no converter available")
def docx_no_converter(t07ctx, monkeypatch):
    from applicant.adapters.resume_tailoring import docx_tailor

    monkeypatch.setattr(docx_tailor.shutil, "which", lambda _name: None)
    t07ctx["docx"] = docx_tailor.DocxTailor(render_mode="auto")


@when("a docx artifact is rendered")
def render_docx_artifact(t07ctx):
    vid = ResumeVariantId(new_id())
    t07ctx["docx_render"] = t07ctx["docx"].render_artifact(vid, "Senior Engineer at Acme.")


@then("the real convert is not attempted")
def real_convert_not_attempted(t07ctx):
    assert t07ctx["docx"]._allow_convert is False


@given("a LaTeX résumé adapter with the render tools installed")
def latex_tools_installed(t07ctx):
    from applicant.adapters.resume_tailoring import latex_tailor

    # Probe the integration seam: a forced real compile requires a TeX engine on PATH,
    # which is absent in the hermetic lane, so this honestly fails (xfail) here.
    t07ctx["latex"] = latex_tailor.LatexTailor(render_mode="on")


@when("a résumé artifact is rendered for real")
def render_latex_for_real(t07ctx):
    vid = ResumeVariantId(new_id())
    source = "\\documentclass{moderncv}\n\\begin{document}\nAcme.\n\\end{document}\n"
    t07ctx["render"] = t07ctx["latex"].render_artifact(vid, source)


@then("a real PDF is produced with every font embedded")
def real_pdf_fonts_embedded(t07ctx):
    # In auto/on mode with NO TeX engine the compile cannot produce a PDF: fidelity is
    # flagged as an approximate preview. This is the genuine red until the binaries are
    # baked into the engine image and exercised in the integration lane.
    render = t07ctx["render"]
    assert render.fidelity_ok is True, render.notes


# ===========================================================================
# #187 — aggressiveness dial backend wired + guardrail proof (GREEN); persist (PENDING)
# ===========================================================================
@given("the truthful-framing dial")
def the_dial(t07ctx):
    t07ctx["dial"] = True


@when("an out-of-range value is applied")
def apply_out_of_range(t07ctx):
    t07ctx["clamped_high"] = clamp_aggressiveness(10_000)
    t07ctx["clamped_low"] = clamp_aggressiveness(-50)


@then("the stored setting is clamped into the supported range")
def setting_clamped(t07ctx):
    assert t07ctx["clamped_high"] == AGGRESSIVENESS_MAX
    assert t07ctx["clamped_low"] == AGGRESSIVENESS_MIN


@when("the most assertive framing is requested")
def request_assertive(t07ctx):
    t07ctx["directive"] = aggressiveness_directive(AGGRESSIVENESS_MAX)


@then("the generation directive still forbids adding any unsupported claim")
def directive_forbids_fabrication(t07ctx):
    directive = t07ctx["directive"].lower()
    # The dial only biases framing; the truthfulness constraint is never relaxed.
    assert "never add a claim that is not in the source" in directive


@given("a material service with no model wired")
def material_service_no_llm(t07ctx):
    t07ctx["svc"] = _material_service()


@when("the operator sets an above-maximum aggressiveness")
def set_above_max(t07ctx):
    t07ctx["returned"] = t07ctx["svc"].set_aggressiveness(AGGRESSIVENESS_MAX + 500)


@then("the service reports the clamped maximum")
def service_clamped_max(t07ctx):
    assert t07ctx["returned"] == AGGRESSIVENESS_MAX
    assert t07ctx["svc"].aggressiveness == AGGRESSIVENESS_MAX


@given("a material service with a chosen aggressiveness for a job search")
def service_chosen_aggressiveness(t07ctx):
    from applicant.adapters.storage.in_memory import InMemoryStorage

    t07ctx["storage"] = InMemoryStorage()
    t07ctx["campaign_id"] = CampaignId(new_id())
    svc = _material_service(t07ctx["storage"])
    svc.set_aggressiveness(80)
    t07ctx["chosen"] = 80


@when("a fresh service is built for the same job search")
def fresh_service_same_campaign(t07ctx):
    svc = _material_service(t07ctx["storage"])
    # Per-campaign persistence is not implemented: a fresh service must RECALL the
    # chosen value from storage. Probe the intended seam (a loader keyed by campaign).
    loader = getattr(svc, "load_aggressiveness", None)
    if loader is None:
        raise AttributeError("MaterialService.load_aggressiveness not implemented yet")
    t07ctx["recalled"] = loader(t07ctx["campaign_id"])


@then("it recalls the previously chosen aggressiveness")
def recalls_chosen(t07ctx):
    assert t07ctx["recalled"] == t07ctx["chosen"]


# ===========================================================================
# #197 — document attachment types (core kinds GREEN; portfolio/attachment PENDING)
# ===========================================================================
@given("the generated-document type catalogue")
def document_type_catalogue(t07ctx):
    t07ctx["types"] = {t.value for t in DocumentType}


@when("the supported document kinds are listed")
def list_document_kinds(t07ctx):
    t07ctx["listed"] = t07ctx["types"]


@then("résumé, cover letter, and screening answer are all present")
def core_kinds_present(t07ctx):
    assert {"resume", "cover_letter", "screening_answer"} <= t07ctx["listed"]


@when("a portfolio attachment kind is requested")
def request_portfolio_kind(t07ctx):
    # No portfolio/attachment type exists in DocumentType yet — genuine red.
    members = {t.name for t in DocumentType}
    if "PORTFOLIO" not in members and "ATTACHMENT" not in members:
        raise AttributeError("DocumentType has no portfolio/attachment kind yet")
    t07ctx["portfolio_kind"] = True


@then("the document model recognizes it as a managed attachment type")
def portfolio_recognized(t07ctx):
    assert t07ctx.get("portfolio_kind") is True


@given("a campaign that allows reference lists and transcripts")
def campaign_allows_attachments(t07ctx):
    from applicant.adapters.storage.in_memory import InMemoryStorage

    t07ctx["storage"] = InMemoryStorage()
    t07ctx["campaign_id"] = CampaignId(new_id())


@when("such an attachment is stored against the campaign")
def store_attachment(t07ctx):
    # There is no campaign-attachment repository — probe the intended seam.
    repo = getattr(t07ctx["storage"], "campaign_attachments", None)
    if repo is None:
        raise AttributeError("no campaign_attachments repository on storage yet")
    t07ctx["attachment_repo"] = repo


@then("the attachment is retrievable as a managed campaign document")
def attachment_retrievable(t07ctx):
    assert t07ctx.get("attachment_repo") is not None


# ===========================================================================
# #246 — truthfulness guard hard-enforced (GREEN); silent-exception counter (PENDING)
# ===========================================================================
@given("a material service over the true candidate source")
def service_over_true_source(t07ctx):
    t07ctx["svc"] = _material_service()
    t07ctx["true_source"] = "Python developer. Built REST APIs. Postgres."


@when("generated text claims a skill absent from that source")
def generated_claims_absent_skill(t07ctx):
    t07ctx["generated"] = "Expert in Kubernetes and Terraform orchestration."


@then("the fabrication guard rejects it rather than degrading silently")
def fabrication_rejected(t07ctx):
    # STRICT pins the hard-reject contract. Under the P1-13 BALANCED default the same
    # detection surfaces the claim for review instead of raising (a human approves
    # every send); the guard still RUNS either way — it never degrades silently.
    from applicant.core.rules.truthfulness import TruthPolicy

    with pytest.raises(TruthfulnessViolation):
        t07ctx["svc"].assert_no_fabrication(
            t07ctx["true_source"], t07ctx["generated"], policy=TruthPolicy.STRICT
        )


@when("a variant is generated from a truthful source toward a job description")
def generate_variant_truthful(t07ctx):
    src = "Python developer. Built REST APIs with FastAPI. Postgres database work."
    # Deterministic fallback (no LLM): reframes the true source toward the JD terms,
    # surfacing only supported terms and never injecting an unsupported one.
    t07ctx["body"] = t07ctx["svc"].reframe_truthfully(src, ["FastAPI", "Kubernetes"])
    t07ctx["true_source"] = src


@then("the generated body adds no claim absent from the source")
def body_no_fabrication(t07ctx):
    flagged = t07ctx["svc"].detect_fabrication(t07ctx["true_source"], t07ctx["body"])
    assert flagged == [], f"deterministic reframe leaked a fabrication: {flagged!r}"


@given("a material service that counts silent degradations")
def service_counts_degradations(t07ctx):
    t07ctx["svc"] = _material_service()


@when("silent failures cross the diagnostic threshold")
def silent_failures_cross_threshold(t07ctx):
    # No silent-exception counter / diagnostic exists in MaterialService — probe the
    # intended seam (a counter attribute the service would expose).
    counter = getattr(t07ctx["svc"], "silent_failure_count", None)
    if counter is None:
        raise AttributeError("MaterialService has no silent_failure_count yet")
    t07ctx["counter"] = counter


@then("a diagnostic event is surfaced rather than producing empty output")
def diagnostic_surfaced(t07ctx):
    emitter = getattr(t07ctx["svc"], "emit_degradation_diagnostic", None)
    assert emitter is not None, "no degradation-diagnostic emitter implemented yet"


# ===========================================================================
# #272 — dormant registry records the surface (GREEN); markup follows registry (PENDING)
# ===========================================================================
@given("the dormant-surface registry")
def dormant_registry(t07ctx):
    from applicant.dormant import DORMANT_SURFACES

    t07ctx["surfaces"] = {s.key: s for s in DORMANT_SURFACES}


@when("the résumé-aggressiveness surface is looked up")
def lookup_aggressiveness_surface(t07ctx):
    t07ctx["surface"] = t07ctx["surfaces"].get("resume_aggressiveness")


@then("it is recorded as a live surface")
def surface_is_live(t07ctx):
    from applicant.dormant import STATUS_LIVE

    surface = t07ctx["surface"]
    assert surface is not None
    assert surface.status == STATUS_LIVE


@given("the résumé-aggressiveness control markup")
def aggressiveness_markup(t07ctx):
    from pathlib import Path

    index = (
        Path(__file__).resolve().parents[3]
        / "workspace"
        / "static"
        / "index.html"
    )
    t07ctx["markup"] = index.read_text(encoding="utf-8")


@when("the surface is read for a hardcoded disabled state")
def read_hardcoded_disabled(t07ctx):
    import re

    markup = t07ctx["markup"]
    m = re.search(r"<input[^>]*id=\"applicant-aggr-slider\"[^>]*>", markup)
    t07ctx["slider_tag"] = m.group(0) if m else ""


@then("the control is not statically disabled in the markup")
def control_not_static_disabled(t07ctx):
    tag = t07ctx["slider_tag"]
    assert tag, "aggressiveness slider not found in markup"
    # Today the slider ships hardcoded `disabled` rather than driven by the registry
    # status — genuine red until the markup/JS derives operability from the registry.
    assert "disabled" not in tag, f"slider hardcoded disabled: {tag}"


# ===========================================================================
# #273 — suggestion type exists (GREEN); engine surfaces suggestions (PENDING)
# ===========================================================================
@given("the advanced-learning attribute suggestion")
def advanced_learning_suggestion(t07ctx):
    mod = importlib.import_module(
        "applicant.application.services.learning_advanced"
    )
    t07ctx["learning_mod"] = mod


@when("an attribute value is cross-referenced from inputs")
def cross_reference_value(t07ctx):
    t07ctx["proposal_cls"] = getattr(t07ctx["learning_mod"], "AttributeProposal", None)


@then("a proposed attribute suggestion type exists to carry it")
def proposal_type_exists(t07ctx):
    assert t07ctx["proposal_cls"] is not None
    # The proposal carries the proposed name/value (FR-LEARN-4).
    fields = getattr(t07ctx["proposal_cls"], "__dataclass_fields__", {})
    assert "name" in fields and "value" in fields


@given("the engine setup/profile status surface")
def engine_status_surface(t07ctx, app_client):
    t07ctx["client"] = app_client


@when("the status payload is inspected for pending attribute suggestions")
def inspect_status_for_suggestions(t07ctx):
    # The front-door suggested-attribute card reads suggestions off the status payload
    # (suggested_attributes / pending_attributes). No engine endpoint exposes them yet,
    # so probe the engine status for that key — genuine red until it is surfaced.
    client = t07ctx["client"]
    keys: set[str] = set()
    for path in ("/api/setup/status", "/api/attributes/status", "/api/onboarding/status"):
        resp = client.get(path)
        if resp.status_code == 200:
            try:
                keys |= set(resp.json().keys())
            except (ValueError, AttributeError):
                pass
    t07ctx["status_keys"] = keys


@then("proposed attributes are exposed for the approval card to display")
def suggestions_exposed(t07ctx):
    keys = t07ctx["status_keys"]
    assert "suggested_attributes" in keys or "pending_attributes" in keys, (
        f"engine status exposes no pending attribute suggestions; keys={sorted(keys)}"
    )


# ===========================================================================
# #289 — variant fit score (GREEN); submission target + conversion (PENDING)
# ===========================================================================
@given("a résumé variant scored against a job description")
def variant_scored(t07ctx):
    t07ctx["svc"] = _material_service()
    t07ctx["variant"] = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=CampaignId(new_id()),
        storage_path="artifacts/base.tex",
        approved=True,
    )
    t07ctx["posting_id"] = JobPostingId(new_id())


@when("the fit coverage is computed")
def compute_fit_coverage(t07ctx):
    source = "Python developer with FastAPI and Postgres experience."
    t07ctx["fit"] = t07ctx["svc"].score_fit(
        t07ctx["variant"], t07ctx["posting_id"], ["FastAPI", "Postgres"], source
    )


@then("the variant records a coverage score for that posting")
def variant_records_coverage(t07ctx):
    fit = t07ctx["fit"]
    assert fit.variant_id == t07ctx["variant"].id
    assert fit.posting_id == t07ctx["posting_id"]
    assert 0.0 <= fit.coverage <= 1.0
    assert fit.coverage > 0.0  # both terms are present in the source


@given("a résumé variant stored for a campaign")
def variant_stored(t07ctx):
    t07ctx["variant"] = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=CampaignId(new_id()),
        storage_path="artifacts/base.tex",
    )


@when("the variant is inspected for its submission target")
def inspect_submission_target(t07ctx):
    # No "submitted to which job" field on the variant — probe the intended attribute.
    target = getattr(t07ctx["variant"], "submitted_posting_id", None)
    if target is None and not hasattr(t07ctx["variant"], "submitted_posting_id"):
        raise AttributeError("ResumeVariant has no submitted_posting_id yet")
    t07ctx["submission_target"] = target


@then("it records which job posting it was submitted to")
def variant_records_submission(t07ctx):
    assert t07ctx["submission_target"] is not None


@given("a résumé variant with submissions and outcomes")
def variant_with_outcomes(t07ctx):
    t07ctx["variant"] = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=CampaignId(new_id()),
        storage_path="artifacts/base.tex",
    )


@when("the variant is inspected for its conversion rate")
def inspect_conversion_rate(t07ctx):
    rate = getattr(t07ctx["variant"], "conversion_rate", None)
    if rate is None and not hasattr(t07ctx["variant"], "conversion_rate"):
        raise AttributeError("ResumeVariant has no conversion_rate yet")
    t07ctx["conversion_rate"] = rate


@then("it reports how many submissions led to interviews")
def variant_reports_conversion(t07ctx):
    assert t07ctx["conversion_rate"] is not None


# ===========================================================================
# #293 — variant lineage (GREEN); promote-to-base + templates (PENDING)
# ===========================================================================
@given("a résumé variant forked from a parent")
def variant_forked(t07ctx):
    from applicant.adapters.storage.in_memory import InMemoryStorage

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    parent = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="artifacts/parent.tex",
        approved=True,
    )
    child = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="artifacts/child.tex",
        parent_id=parent.id,
    )
    storage.resume_variants.add(parent)
    storage.resume_variants.add(child)
    storage.commit()
    t07ctx["svc"] = _material_service(storage)
    t07ctx["parent"] = parent
    t07ctx["child"] = child


@when("the lineage chain is walked")
def walk_lineage(t07ctx):
    t07ctx["chain"] = t07ctx["svc"].lineage(t07ctx["child"])


@then("the parent appears in the variant's lineage")
def parent_in_lineage(t07ctx):
    ids = {str(v.id) for v in t07ctx["chain"]}
    assert str(t07ctx["parent"].id) in ids
    assert str(t07ctx["child"].id) in ids


@given("a stored résumé variant in the document library")
def variant_in_doclib(t07ctx):
    t07ctx["svc"] = _material_service()
    t07ctx["variant"] = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=CampaignId(new_id()),
        storage_path="artifacts/base.tex",
        approved=True,
    )


@when("the operator promotes it to the new base résumé")
def promote_to_base(t07ctx):
    # No "use THIS résumé as my new base" path exists — probe the intended seam.
    promote = getattr(t07ctx["svc"], "promote_to_base_resume", None)
    if promote is None:
        raise AttributeError("MaterialService has no promote_to_base_resume yet")
    t07ctx["promote"] = promote


@then("the engine adopts it as the base it tailors from")
def engine_adopts_base(t07ctx):
    assert t07ctx.get("promote") is not None


@given("a cover-letter template with merge fields")
def cover_letter_template(t07ctx):
    t07ctx["template"] = "Dear {{company}}, I am applying for {{role}}."


@when("the engine fills the template for an application")
def fill_template(t07ctx):
    svc = _material_service()
    # No template-library / merge-field filler exists — probe the intended seam.
    filler = getattr(svc, "fill_cover_letter_template", None)
    if filler is None:
        raise AttributeError("MaterialService has no fill_cover_letter_template yet")
    t07ctx["filled"] = filler(t07ctx["template"], {"company": "Acme", "role": "Engineer"})


@then("the merge fields are populated from the application context")
def merge_fields_populated(t07ctx):
    filled = t07ctx["filled"]
    assert "Acme" in filled and "Engineer" in filled
    assert "{{" not in filled
