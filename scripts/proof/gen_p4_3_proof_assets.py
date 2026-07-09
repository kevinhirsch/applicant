#!/usr/bin/env python
"""P4-3 proof-asset generator: a shareable digest-email sample + a before/after
tailoring diff, both rendered from REAL product code over the P0-2 DEMO_MODE seed.

Nothing here re-implements product logic — it only assembles seed data through the
engine's own rendering paths, exactly as `docs/proof/p1-2/README.md`'s proof-run
precedent does for the pre-fill leg:

* the digest sample is `DigestService.render_email()` (`application/services/
  digest_service.py`) — the SAME branded template P1-4 ships (masthead, preheader,
  inline-styled card list) — fed the seven real `dev_seed` demo postings;
* the tailoring diff is `LatexTailor.render_redline()` (`adapters/resume_tailoring/
  latex_tailor.py`) — the SAME per-line `difflib.SequenceMatcher` diff the redline
  review UI (`review.js` / `documentLibrary.js`) renders, using the exact
  `redline-add`/`redline-sub`/`redline-eq` classes those surfaces already use — fed
  the real demo-seed base-résumé text, the tailored material, and the real
  `RevisionSession` redline_state additions/subtractions.

Hermetic: builds an `InMemoryStorage` demo bundle (`dev_seed.build_demo_bundle`),
no DB/network/LLM/TeX required. Re-running regenerates both output copies from the
same inputs (idempotent, deterministic).

Usage:
    uv run python scripts/proof/gen_p4_3_proof_assets.py

Writes two files to BOTH locations (kept identical by construction — a single
generation pass, not hand-maintained copies):
    docs/proof/p4-3/digest-sample.html        workspace/static/proof/digest-sample.html
    docs/proof/p4-3/tailoring-diff.html       workspace/static/proof/tailoring-diff.html

The `workspace/static/proof/` copies are the reachable ones — served by the existing
`/static` mount (no new route), linked from `workspace/static/landing.html`'s `#proof`
strip and hero slot (P4-2). The `docs/proof/p4-3/` copies are the doc-reviewable,
citable record, matching the P1-2 proof-run precedent's directory convention.
"""

from __future__ import annotations

import html
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_OUT = _REPO_ROOT / "docs" / "proof" / "p4-3"
_STATIC_OUT = _REPO_ROOT / "workspace" / "static" / "proof"

_PAGE_CSS = """
  :root { color-scheme: light dark; }
  body { margin:0; background:#f4f5f6; font-family: Arial, Helvetica, sans-serif; color:#111; }
  @media (prefers-color-scheme: dark) {
    body { background:#0f1115; color:#e6e8eb; }
  }
  .wrap { max-width: 760px; margin: 0 auto; padding: 28px 16px 60px; }
  .banner {
    font-size: 12.5px; line-height:1.6; background:#fff8e1; color:#6b5b12;
    border:1px solid #f0e2a6; border-radius:8px; padding:12px 14px; margin-bottom:22px;
  }
  @media (prefers-color-scheme: dark) {
    .banner { background:#2a250f; color:#e8d68a; border-color:#4a3f1a; }
  }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .sub { font-size: 13.5px; color:#666; margin: 0 0 24px; }
  @media (prefers-color-scheme: dark) { .sub { color:#a7acb3; } }
  .stage { margin: 28px 0 8px; }
  .stage h2 { font-size: 16px; margin: 0 0 4px; }
  .stage p { font-size: 13px; color:#555; line-height:1.6; margin: 0 0 10px; }
  @media (prefers-color-scheme: dark) { .stage p { color:#b7bcc3; } }
  .callout {
    font-size: 12.5px; line-height:1.6; background:#eef4ff; color:#1a3f7a;
    border:1px solid #cfe0fb; border-radius:8px; padding:10px 12px; margin: 10px 0 16px;
  }
  @media (prefers-color-scheme: dark) {
    .callout { background:#0f1f3a; color:#a9c6ff; border-color:#1e355c; }
  }
  .redline {
    white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px; line-height: 1.65; background:#fff; border:1px solid #e2e4e8;
    border-radius: 8px; padding: 16px;
  }
  @media (prefers-color-scheme: dark) {
    .redline { background:#161a20; border-color:#2a2f38; }
  }
  .redline-add { background:#e6ffed; color:#045d1e; }
  .redline-sub { background:#ffeef0; color:#9e1c23; text-decoration:line-through; }
  .redline-eq { color:#444; }
  @media (prefers-color-scheme: dark) {
    .redline-add { background:#0d3320; color:#7ee2a0; }
    .redline-sub { background:#3a1418; color:#ff9aa2; }
    .redline-eq { color:#aab0b8; }
  }
  .turn { font-size: 12.5px; color:#555; border-left: 3px solid #cfd4db; padding: 4px 0 4px 10px; margin: 8px 0; }
  @media (prefers-color-scheme: dark) { .turn { color:#b7bcc3; border-left-color:#3a4049; } }
  .turn b { color:inherit; }
  footer { margin-top: 34px; font-size: 11.5px; color:#8a8f98; }
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        f"<style>{_PAGE_CSS}</style></head><body><div class=\"wrap\">{body}</div></body></html>\n"
    )


# --- asset 1: the branded digest email, populated from the real demo seed ------


def build_digest_sample_html() -> str:
    from applicant.adapters.storage.in_memory import InMemoryStorage
    from applicant.application.services import dev_seed as seed
    from applicant.application.services.digest_service import DigestService
    from applicant.core.entities.onboarding_profile import OnboardingProfile
    from applicant.core.entities.viability_scoring import ViabilityScoring
    from applicant.core.ids import CampaignId, OnboardingProfileId

    class _DemoScoring:
        """Reads the SAME score/rationale the demo seed already stamped onto each
        posting (`dev_seed._DEMO_POSTINGS`) instead of re-deriving one — the digest
        sample must show the real seeded numbers, not a fresh invented score."""

        def score_posting(self, posting, criteria=None):
            return ViabilityScoring(
                posting_id=posting.id,
                score=float(posting.viability_score or 0.0),
                rationale=str((posting.rationale or {}).get("summary") or ""),
            )

        def score_for_digest(self, posting, criteria=None):
            return self.score_posting(posting, criteria)

        def is_viable(self, scoring) -> bool:
            return True  # every demo posting was curated above the bar

    bundle = seed.build_demo_bundle()
    storage = InMemoryStorage()
    seed.persist(storage, bundle)
    # Real base-résumé text on file (the same seed intake `ensure_demo_apply_ready`
    # writes for a live campaign) so the digest's keyword-coverage chip renders too.
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId("demo-onboarding-profile"),
            campaign_id=CampaignId(seed.DEMO_CAMPAIGN_ID),
            intake={"base_resume": {"raw_text": seed._DEMO_BASE_RESUME_TEXT}},
        )
    )

    digest = DigestService(storage, notification=None, scoring=_DemoScoring())
    payload = digest.render_email(CampaignId(seed.DEMO_CAMPAIGN_ID))

    banner = (
        '<div class="banner"><strong>Proof sample</strong> &mdash; this is Applicant\'s '
        "real digest email template (P1-4's branded shell, unmodified), rendered here "
        "with the product's own seeded demo data (P0-2 <code>DEMO_MODE</code>), saved as "
        "a static file for sharing or screenshotting. It is not a live inbox message and "
        "sends nothing.</div>"
    )
    return _page(payload["subject"], banner + payload["html"])


# --- asset 2: the before/after tailoring diff, computed by the real diff engine --


def build_tailoring_diff_html() -> str:
    from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
    from applicant.application.services import dev_seed as seed
    from applicant.core.ids import ResumeVariantId

    tailor = LatexTailor()

    all_postings = seed.build_demo_postings()
    postings_by_id = {p.id: p for p in all_postings}
    resume_variant = seed.build_demo_resume_variant()
    applications = seed.build_demo_applications(all_postings, resume_variant)
    review_app = next(a for a in applications if str(a.resume_variant_id or "") == str(resume_variant.id))
    posting = postings_by_id[review_app.posting_id]
    material = seed.build_demo_material(str(review_app.id))
    revision = seed.build_demo_revision_session(str(material.id))

    base_text = seed._DEMO_BASE_RESUME_TEXT
    tailored_text = material.content

    # Stage 2 (the redline session) is reconstructed from the REAL redline_state
    # additions/subtractions the demo seed carries (`build_demo_revision_session`) —
    # not invented prose. `removed[0]` was a second Umbrella bullet the tailored
    # draft (`tailored_text`) never actually contained (the seed's `redline_state`
    # narrates a past turn, it isn't itself a document), so the "before this redline"
    # version is reassembled here by appending it back before diffing, and the
    # "after" version is `tailored_text` with the real `added[0]` bullet appended —
    # the same two strings the seed already stamped on `redline_state`.
    added_line = revision.redline_state["added"][0]
    removed_line = revision.redline_state["removed"][0]
    pre_redline_text = tailored_text.rstrip("\n") + f"\n- {removed_line}\n"
    post_redline_text = tailored_text.rstrip("\n") + f"\n- {added_line}\n"

    stage1 = tailor.render_redline(ResumeVariantId(str(resume_variant.id)), base_text, tailored_text)
    stage2 = tailor.render_redline(ResumeVariantId(str(resume_variant.id)), pre_redline_text, post_redline_text)

    free_text_turn = next(t for t in revision.turns if t.kind == "free_text")
    missing_terms = ", ".join(resume_variant.fit_scores.get("missing_terms", []))
    coverage_pct = round(float(resume_variant.fit_scores.get("coverage", 0)) * 100)

    body = f"""
<h1>Before / after: tailoring a real demo résumé</h1>
<p class="sub">Real demo-seed content (P0-2 <code>DEMO_MODE</code>) run through Applicant's own
tailoring-diff engine (<code>LatexTailor.render_redline</code>, the exact per-line
<code>difflib</code> diff the redline review screen renders) &mdash; not a mockup. Target posting:
<strong>{html.escape(posting.title)}</strong> at <strong>{html.escape(posting.company)}</strong>
({html.escape(posting.location)}, {html.escape(posting.salary or "")}).</p>

<div class="stage">
  <h2>Stage 1 &mdash; base résumé &rarr; AI-tailored draft</h2>
  <p>What you uploaded (plain, untargeted notes) versus the résumé Applicant generated for this
  specific posting. Every line changed because the base text was unstructured prose, not a
  formatted résumé &mdash; tailoring here means restructuring around the role, not tweaking words.</p>
  <div class="redline">{stage1.rendered_html}</div>
</div>

<div class="stage">
  <h2>Stage 2 &mdash; your redline pass on the tailored draft</h2>
  <p>The résumé variant's own fit-score flagged a coverage gap before you ever opened the redline
  screen: {coverage_pct}% JD coverage, missing terms <strong>{html.escape(missing_terms)}</strong>.
  The add/subtract turn below is the review session closing exactly that gap.</p>
  <div class="callout">Fit-score gap &rarr; redline fix: "Kubernetes" was flagged missing at
  {coverage_pct}% coverage; the "add" turn below adds a Kubernetes bullet back in.</div>
  <div class="redline">{stage2.rendered_html}</div>
  <div class="turn"><b>Also requested in this session (free-text turn, not a line edit):</b><br>
  &ldquo;{html.escape(free_text_turn.instruction)}&rdquo; &rarr;
  {html.escape(free_text_turn.ai_response)}</div>
</div>

<footer>Generated by <code>scripts/proof/gen_p4_3_proof_assets.py</code> from the P0-2 demo seed
(<code>applicant.application.services.dev_seed</code>) — real seeded strings throughout, no
placeholder text.</footer>
"""
    return _page("Before / after: tailoring diff (demo)", body)


# --- asset 3: a reachable HTML mirror of the demo-script storyboard ------------


def build_demo_script_html() -> str:
    """A front-door-reachable rendering of `docs/proof/demo-script.md`.

    The markdown file is the canonical, doc-reviewable storyboard (task asked for
    it at that exact path); this is only a reachability mirror — literally the
    same text, monospaced — so a landing-page visitor can read the shot list
    today even though the recording itself doesn't exist yet.
    """
    script_path = _REPO_ROOT / "docs" / "proof" / "demo-script.md"
    text = script_path.read_text(encoding="utf-8")
    banner = (
        '<div class="banner"><strong>Proof sample</strong> &mdash; the 2-minute demo '
        "video itself needs a live stack + owner recording (the one remaining piece "
        "of this story); this is the shot-by-shot script for it, verbatim from "
        "<code>docs/proof/demo-script.md</code>.</div>"
    )
    pre = f'<pre style="white-space:pre-wrap;font-size:12.5px;line-height:1.6;">{html.escape(text)}</pre>'
    return _page("Demo video storyboard (recording pending)", banner + pre)


def main() -> int:
    _DOCS_OUT.mkdir(parents=True, exist_ok=True)
    _STATIC_OUT.mkdir(parents=True, exist_ok=True)

    digest_html = build_digest_sample_html()
    diff_html = build_tailoring_diff_html()

    for name, content in (
        ("digest-sample.html", digest_html),
        ("tailoring-diff.html", diff_html),
    ):
        for out_dir in (_DOCS_OUT, _STATIC_OUT):
            (out_dir / name).write_text(content, encoding="utf-8")
            print(f"wrote {out_dir / name}")

    # Reachability mirror only — no docs/ copy needed, docs/proof/demo-script.md
    # already IS the canonical file this reads from.
    script_html = build_demo_script_html()
    (_STATIC_OUT / "demo-script.html").write_text(script_html, encoding="utf-8")
    print(f"wrote {_STATIC_OUT / 'demo-script.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
