"""Regression coverage for the activation-funnel audit
(``docs/design/audits/exhaustive2/09_activation_funnel.md``), confined to this
batch's file lane: ``static/landing.html`` and ``static/js/applicantOnboarding.js``
(the landing page and the first-run OOBE wizard).

Follows the established convention (``test_applicant_round2_wave2_firstlight.py``,
``test_applicant_profile_gaps_checklist_js.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket. Each assertion here was verified, by hand, to go red when the underlying
fix is reverted (temporarily swap in the file-copy backup taken before this
batch, rerun, see a real ``AssertionError``, then restore the fixed version —
never ``git stash``).

What this batch adds:

* Landing page (audit items A#3, A#4, A#6):
  - a serious "what it does / what it never does" section (`#trust`), reusing
    the wizard's NEVER_DOES wording verbatim, ahead of the joke testimonials.
  - the "Get started" section now also offers the one-liner install script and
    a `/login` path for an already-running instance, instead of only `git clone`.
  - the two `<video>` previews pointing at chat.webm/email.mp4 (files that were
    never shipped, so those panels silently never played) are dropped; all
    three preview panels now behave like the (always-worked) Cookbook one.
* Onboarding wizard (audit items D16, D27/D33, D45, D47, D50, D52/D56, D71,
  D73, D82):
  - a persistent "your progress saves automatically" reassurance line.
  - a skip-consequence hint on the one step that actually gates beginning.
  - the "You're all set!" screen states the default throughput and offers a
    "Complete your profile" jump when profile essentials are still missing.
  - `campaign_criteria` moved right after `target_roles`; `references` moved
    to the very end of the intake order.
  - the phone field is `type=tel` with a placeholder; the compensation section
    uses a numeric salary floor + a real currency dropdown + a privacy note;
    the work-authorization country field offers a suggestion datalist.
  - LinkedIn/portfolio URLs are normalized to include a scheme on save.
  - the "Connect a model" step states which provider/model it is about to
    connect before opening the engine gate.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
LANDING = WORKSPACE_DIR / "static" / "landing.html"
ONBOARDING_JS = WORKSPACE_DIR / "static" / "js" / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace counting
    (mirrors test_applicant_round2_wave2_firstlight.py's helper — needed because
    these functions nest arrow-function braces a non-greedy line-based regex
    can't balance reliably)."""
    m = re.search(rf"(?:async )?function {re.escape(name)}\([^)]*\)\s*\{{", src)
    assert m, f"expected to find function {name}"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


# ── landing.html: the serious trust section leads the joke testimonials ────


def test_trust_section_exists_before_testimonials_and_is_nav_reachable():
    html = _read(LANDING)
    trust_idx = html.find('<section id="trust"')
    testimonials_idx = html.find('<section id="testimonials"')
    assert trust_idx != -1, "expected a #trust section"
    assert testimonials_idx != -1, "expected the #testimonials section"
    assert trust_idx < testimonials_idx, (
        "expected the serious #trust section to precede the joke testimonials"
    )
    nav_match = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert nav_match, "no <nav> section found"
    assert re.search(r'href=["\']#trust["\']', nav_match.group(0)), (
        "expected a nav link to #trust so the section is actually reachable"
    )


def test_trust_section_reuses_the_never_does_wording_verbatim():
    """The wizard's NEVER_DOES list (static/js/applicantOnboarding.js) is the
    canonical wording for what Applicant never does; the landing page's trust
    section must match it verbatim, not a paraphrase that could silently drift
    out of sync with the actual product contract."""
    html = _read(LANDING)
    trust_match = re.search(r'<section id="trust".*?</section>', html, re.DOTALL)
    assert trust_match, "expected a #trust section"
    section = trust_match.group(0)

    js = _read(ONBOARDING_JS)
    never_does_block = re.search(r"const NEVER_DOES = \[(.*?)\n\];", js, re.DOTALL)
    assert never_does_block, "expected NEVER_DOES in applicantOnboarding.js"
    # Pull each single-quoted string literal out of the array.
    items = re.findall(r"'([^']+)'", never_does_block.group(1))
    assert len(items) == 4, f"expected 4 NEVER_DOES entries, found {len(items)}"
    for item in items:
        # The landing page renders &mdash; for the JS source's literal em dash,
        # so compare on the dash-agnostic prefix/suffix instead of full equality.
        prefix = item.split("—")[0].strip()
        assert prefix in section, (
            f"expected the trust section to reuse NEVER_DOES wording {item!r} verbatim"
        )


def test_trust_section_has_no_upstream_fork_codename():
    html = _read(LANDING)
    trust_match = re.search(r'<section id="trust".*?</section>', html, re.DOTALL)
    assert trust_match
    lowered = trust_match.group(0).lower()
    for codename in ("firehouse", "orwell", "odysseus", "smokey"):
        assert codename not in lowered


# ── landing.html: "Get started" offers more than a bare git clone ──────────


def test_get_started_section_offers_install_script_and_signin_alternatives():
    html = _read(LANDING)
    start_match = re.search(r'<section id="start".*?</section>', html, re.DOTALL)
    assert start_match, "expected the #start section"
    section = start_match.group(0)
    assert "install.sh" in section, (
        "expected the get-started section to mention the one-liner install script, "
        "not only the raw git clone"
    )
    assert re.search(r'href="/login"', section), (
        "expected a /login path for a visitor looking at an already-running instance"
    )


# ── landing.html: dead video references removed ─────────────────────────────


def test_no_dangling_video_source_references():
    """chat.webm/chat.mp4/email.webm/email.mp4 were never shipped in
    workspace/static/, so the <video> elements pointing at them silently never
    played. They must be removed rather than left as broken references."""
    html = _read(LANDING)
    for asset in ("chat.webm", "chat.mp4", "email.webm", "email.mp4"):
        assert asset not in html, f"expected no dangling reference to {asset!r}"
    assert "<video" not in html, "expected the non-functional <video> previews removed"


# ── onboarding wizard: progress-saves reassurance (D82) ─────────────────────


def test_overlay_states_progress_saves_automatically():
    body = _find_function(_read(ONBOARDING_JS), "_buildOverlay")
    assert "saves automatically" in body.lower()


# ── onboarding wizard: skip-consequence hint on the required step (D16) ────


def test_nav_warns_what_skipping_the_required_step_costs():
    body = _find_function(_read(ONBOARDING_JS), "_renderNav")
    assert "ao-skip-hint" in body
    assert re.search(r"cur\.required && !cur\.done\(_status\)", body), (
        "expected the hint to be conditioned on the current step being required "
        "and not yet done"
    )
    assert "can" in body.lower() and "start" in body.lower()


# ── onboarding wizard: completion receipt + profile jump (D71/D73) ─────────


def _ready_branch(body: str) -> str:
    # Anchor on the start of the `if (!missing.length) { ... }` block itself
    # (not the "You're all set!" copy inside it) — `receiptLine`/`profileJumpBtn`
    # are template-literal VARIABLES assigned before the _setBody(...) call that
    # actually renders "You're all set!", so anchoring there would exclude their
    # definitions (and the literal "15"/"30"/"Complete your profile" text living
    # inside them) from the slice.
    ready_idx = body.find("if (!missing.length) {")
    almost_idx = body.find("Almost there")
    assert ready_idx != -1 and almost_idx != -1 and ready_idx < almost_idx
    return body[ready_idx:almost_idx]


def test_finish_ready_screen_states_the_default_throughput():
    body = _find_function(_read(ONBOARDING_JS), "_finish")
    ready_branch = _ready_branch(body)
    assert "15" in ready_branch and "30" in ready_branch, (
        "expected the ready screen to state the default throughput (15/day, cap 30)"
    )
    assert "Campaigns" in ready_branch, (
        "expected a pointer to where the pace is adjustable"
    )


def test_finish_ready_screen_offers_a_profile_jump_when_essentials_missing():
    body = _find_function(_read(ONBOARDING_JS), "_finish")
    ready_branch = _ready_branch(body)
    assert "ao-finish-profile" in ready_branch
    assert "Complete your profile" in ready_branch
    # Must be gated on the SAME not-ready condition the prose line already uses.
    assert re.search(r"!ready && applyMissing\.length", ready_branch)
    # The completion flag must still be set before the jump button is wired
    # (regression guard for the pre-existing first-light contract).
    flag_idx = ready_branch.index("_justCompletedSetup = true;")
    onclick_idx = ready_branch.index("document.getElementById('ao-finish').onclick = _dismiss;")
    assert flag_idx < onclick_idx


# ── onboarding wizard: intake section order (D52/D56) ───────────────────────


def test_intake_sections_reordered_criteria_earlier_references_last():
    src = _read(ONBOARDING_JS)
    m = re.search(r"const INTAKE_SECTIONS = \[(.*?)\n\];", src, re.DOTALL)
    assert m, "expected INTAKE_SECTIONS"
    order = re.findall(r"'([a-z_]+)'", m.group(1))
    assert order[0] == "base_resume", "resume must still lead the intake"
    assert order[-1] == "references", (
        "expected 'references' moved to the very end of the intake order"
    )
    assert order.index("campaign_criteria") == order.index("target_roles") + 1, (
        "expected 'campaign_criteria' to immediately follow 'target_roles'"
    )


# ── onboarding wizard: field-level friction fixes (D45/D47/D50) ────────────


def test_fieldhtml_supports_placeholder_list_and_select_types():
    body = _find_function(_read(ONBOARDING_JS), "_fieldHTML")
    assert "f.placeholder" in body
    assert "f.list" in body and "datalist" in body
    assert "f.type === 'select'" in body


def test_phone_field_is_type_tel_with_placeholder():
    src = _read(ONBOARDING_JS)
    m = re.search(r"identity:\s*\{.*?fields:\s*\[(.*?)\],\s*\},", src, re.DOTALL)
    assert m, "expected the identity SECTION_FORMS entry"
    identity_fields = m.group(1)
    phone_field = re.search(r"\{[^{}]*name:\s*'phone'[^{}]*\}", identity_fields)
    assert phone_field, "expected a phone field in identity"
    assert "type: 'tel'" in phone_field.group(0)
    assert "placeholder:" in phone_field.group(0)


def test_work_authorization_country_field_has_a_country_datalist():
    src = _read(ONBOARDING_JS)
    assert "_COMMON_COUNTRIES" in src
    m = re.search(r"\{[^{}]*name:\s*'authorized_country'[^{}]*\}", src)
    assert m, "expected an authorized_country field spec"
    assert "list:" in m.group(0) and "listOptions:" in m.group(0)


def test_compensation_uses_numeric_floor_and_currency_dropdown_with_privacy_note():
    src = _read(ONBOARDING_JS)
    m = re.search(r"compensation:\s*\{(.*?)\n  \},", src, re.DOTALL)
    assert m, "expected the compensation SECTION_FORMS entry"
    block = m.group(1)
    assert "desc:" in block, "expected a privacy/usage note on the compensation section"
    salary_floor = re.search(r"\{[^{}]*name:\s*'salary_floor'[^{}]*\}", block)
    assert salary_floor and "type: 'number'" in salary_floor.group(0)
    currency = re.search(r"\{[^{}]*name:\s*'currency'[^{}]*\}", block)
    assert currency and "type: 'select'" in currency.group(0) and "options:" in currency.group(0)


# ── onboarding wizard: URL normalization (D46) ──────────────────────────────


def test_collect_form_normalizes_linkedin_and_portfolio_urls():
    body = _find_function(_read(ONBOARDING_JS), "_collectForm")
    assert "_maybeNormalizeUrl" in body
    src = _read(ONBOARDING_JS)
    helper = _find_function(src, "_maybeNormalizeUrl")
    assert "linkedin" in helper and "portfolio" in helper
    assert "https://" in helper


# ── onboarding wizard: provider/model transparency before the gate (D27/D33) ─


def test_llm_step_states_provider_and_model_before_saving():
    body = _find_function(_read(ONBOARDING_JS), "_renderLLM")
    assert "Connecting as" in body
    assert "chosen.model" in body
