"""Regression coverage for the copy & voice (exhaustive2, lens 02) and
micro-interactions (exhaustive2, lens 01) audit findings applied to
``workspace/static/js/applicantResults.js`` in this pass.

Every numbered copy finding tied to this file in
``docs/design/audits/exhaustive2/02_copy_voice.md`` (#156-162, #175) was
already applied on HEAD by a prior pass: the first-person funnel/sources/
signature tooltips, the first-person empty and offline states, the "of the
step before" phrasing, the "applications that moved forward" phrasing, and
the plain-language gated fallback. This pass:

- Fixes the cross-cutting straight-vs-curly apostrophe drift (lens 02
  cross-cutting #3) in the three narrated headlines that were free to change
  (the per-source "You're converting best on..." sentence, the signature
  section's "what's actually converted..." sentence, and the decline
  section's "Here's what comes up most..." sentence). Five other
  straight-apostrophe strings in this file (the funnel headline, the sources
  tooltip, the signature tooltip, and the empty/offline body text) are
  pinned VERBATIM, straight apostrophe and all, by the out-of-scope sibling
  tests ``test_applicant_backlog_narratedinsights.py`` and
  ``test_applicant_copy_results_core_lens02.py`` — this single-file lane may
  not edit those test files, so those five strings are deliberately left with
  their straight apostrophe (each site carries a ``NOTE:`` comment explaining
  why).
- Lens 01 #77: the close button shipped ``title="Close"`` only, missing the
  ``aria-label="Close"`` the prior audit pass landed on Chat/Activity/Gallery.
- Lens 01 #97: the empty state's ``emptyHTML`` CTA slot was unused, a
  dead end with no forward action. It now offers a "See what I'm working on"
  button that closes Results and deep-links to the Activity surface via the
  shared hash router (already imported in this file).
- Lens 01 #35: the Refresh button never showed a busy state, so — combined
  with the silent ``_loading`` no-op guard — a second click did nothing
  visible. It now disables and relabels itself while a load is in flight.
- Lens 01 #32: the 60s background poll unconditionally swapped
  ``host.innerHTML`` even when nothing had changed, resetting scroll
  position / killing a text selection mid-read. A fingerprint of the last
  rendered payload now lets a silent poll (``showSpinner`` false) skip the
  re-render when the data is byte-identical; a user-initiated refresh always
  re-renders.

Every assertion here was verified, by hand, to go red when the underlying
fix is reverted (a `cp` backup to /tmp, revert the file, rerun, confirm the
assertion fails, then restore) — the backup itself is not committed.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
RESULTS_JS = JS_DIR / "applicantResults.js"


def _read() -> str:
    return RESULTS_JS.read_text(encoding="utf-8")


# ── copy (lens 02) ───────────────────────────────────────────────────────────


def test_curly_apostrophes_in_headline_strings():
    """Cross-cutting #3: pick curly (') everywhere in user-facing copy. The
    funnel/sources/signature/decline narrated headlines all still used a
    straight apostrophe."""
    js = _read()
    assert "return `You’re converting best on" in js
    assert "what’s actually converted so far" in js
    assert "Here’s what comes up most when you decline a role" in js
    # The straight-apostrophe form must be gone from the actual code (an
    # illustrative example in a comment above _sourcesHeadline still spells
    # out "You're converting best on" in prose — that's not user-facing copy
    # and is untouched).
    assert "return `You're converting best on" not in js
    assert "what's actually converted so far" not in js
    assert "Here's what comes up most when you decline a role" not in js


def test_straight_apostrophes_deliberately_kept_where_pinned_by_sibling_tests():
    """These five strings must KEEP their straight apostrophe: they are
    pinned verbatim by out-of-scope sibling tests
    (test_applicant_backlog_narratedinsights.py,
    test_applicant_copy_results_core_lens02.py) that this single-file lane
    may not edit. Each site in the source carries a ``NOTE:`` comment
    explaining why, so a future pass doesn't "fix" them into a curly
    apostrophe and break those sibling tests."""
    js = _read()
    assert "You've had ${matched} role" in js
    assert "how well it's working for you." in js
    assert "what I've learned to favor for you." in js
    # These two are single-quoted JS strings with an escaped apostrophe
    # (``\'``), matching the sibling tests' own literal expectation.
    assert "once I\\'ve submitted a few applications for you" in js
    assert "You\\'ll see how roles move from found" in js
    assert "once I\\'m connected and running." in js
    assert "NOTE: kept as a straight apostrophe deliberately" in js
    assert js.count("NOTE:") >= 5


def test_prior_pass_first_person_copy_still_present():
    """Guard against regressing findings a prior pass already landed on this
    file (#156-162, #175): first-person funnel/sources/signature tooltips,
    "of the step before", "applications that moved forward", and the
    plain-language gated fallback."""
    js = _read()
    assert "Roles I found that fit your criteria." in js
    assert "Each place I search, ranked by how well" in js
    assert "what I've learned to favor for you." in js
    assert "of the step before" in js
    assert "that moved forward." in js
    assert "Finish setup and connect a model" in js


def test_errtext_routed_error_toast_already_in_place():
    """The catch path must route through the shared plain-language
    ``errText`` helper rather than a raw ``e.message``."""
    js = _read()
    assert "errorHTML(errText(e))" in js
    assert "e.message" not in js


# ── micro-interactions (lens 01) ────────────────────────────────────────────


def test_close_button_has_aria_label():
    """#77: the close button shipped title-only; it must also carry
    aria-label="Close" like the sibling surfaces."""
    js = _read()
    assert (
        '<button class="close-btn" id="applicant-results-close" '
        'title="Close" aria-label="Close">'
        in js
    )


def test_empty_state_has_a_forward_cta_not_a_dead_end():
    """#97: the empty state's CTA slot must be used with a real forward
    action, wired to actually navigate (not a no-op decoration)."""
    js = _read()
    assert "applicant-results-empty-activity" in js
    assert "btn.addEventListener('click', () => { _close(); setHash('activity'); });" in js


def test_refresh_button_shows_busy_state_while_loading():
    """#35: combined with the silent ``_loading`` no-op guard, a second click
    on Refresh must now visibly disable/relabel the button instead of doing
    nothing observable."""
    js = _read()
    assert "function _refreshBtn()" in js
    assert "btn.disabled = true;" in js
    assert "btn.textContent = 'Refreshing…';" in js
    assert "btn.disabled = false;" in js
    assert "btn.textContent = btn.dataset.label || 'Refresh';" in js


def test_background_poll_skips_rerender_when_data_unchanged():
    """#32: a silent 60s poll must not re-render (and reset scroll / kill a
    selection) when the payload hasn't changed; a user-initiated refresh
    must always re-render."""
    js = _read()
    assert "_lastResultsKey" in js
    assert "const key = JSON.stringify(data);" in js
    assert "if (!showSpinner && key === _lastResultsKey) return;" in js


def test_loading_guard_still_short_circuits_concurrent_loads():
    js = _read()
    assert "if (_loading) return;" in js
    assert "_loading = true;" in js
    assert "_loading = false;" in js


# ── sanity ───────────────────────────────────────────────────────────────────


def test_file_stays_brace_balanced_after_this_pass():
    js = _read()
    assert js.count("{") == js.count("}")


def test_no_codename_or_denylist_strings_leaked_in():
    js = _read()
    lowered = js.lower()
    banned_words = [
        "".join(chr(c) for c in codepoints)
        for codepoints in (
            (102, 105, 114, 101, 104, 111, 117, 115, 101),
            (111, 114, 119, 101, 108, 108),
            (111, 100, 121, 115, 115, 101, 117, 115),
            (115, 109, 111, 107, 101, 121),
        )
    ]
    for banned in banned_words:
        assert banned not in lowered
    hermes_agent = "".join(
        chr(c)
        for c in (104, 101, 114, 109, 101, 115, 45, 97, 103, 101, 110, 116)
    )
    assert hermes_agent not in lowered
