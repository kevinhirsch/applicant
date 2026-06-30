"""Registry of the FR-UIKIT migration tracking items (foundation, cross-cutting, surfaces).

This is plain data shared by two consumers:

* ``tools`` / the one-off feature generator (``scripts`` or scratchpad) that emits the
  ``tests/bdd/features/enhancements/uikit_*.feature`` files from this table, and
* the step module ``test_enh_t13_uikit_steps.py``, which probes each item against the
  real repo tree.

Each item maps a stable key (``F1``..``F7``, ``X1``..``X4``, ``S1``..``S17``) to:

* ``issue``     — the GitHub issue number it tracks.
* ``frref``     — the FR-UIKIT clause(s) it implements.
* ``title``     — the Gherkin ``Feature:`` line.
* ``paths``     — the surface/source file(s), for the feature header comment.
* ``rationale`` — one line for the feature header comment.
* ``baseline``  — a probe that MUST be true TODAY (the un-tagged GREEN scenario).
* ``target``    — a probe that MUST be false today, so the ``@pending`` scenario is an
                  honest xfail; it flips true when the migration lands and the tag drops.

Probes are ``(kind, *args)`` tuples interpreted by ``probe()`` in the step module:

* ``("file_exists", relpath)``        — ``workspace/static/<relpath>`` exists.
* ``("file_contains", relpath, sub)`` — that file exists AND contains ``sub`` (missing file -> False).
* ``("css_contains", sub)``           — ``workspace/static/style.css`` contains ``sub``.
* ``("ci_contains", sub)``            — ``.github/workflows/ci.yml`` contains ``sub``.
* ``("section_present_but_disabled", key)`` — ``applicant_features`` flags that section disabled.

The probes are deliberately coarse structural facts (a vendored module is present; a
surface's markup references the kit's CSS classes) — the same honest-red discipline as the
other enhancement specs (``test_enh_t08_frontend_steps.py``): never ``assert True``.
"""

from __future__ import annotations

# Foundation — vendor the kits (verbatim, then white-label rename to appkit*).
_FOUNDATION = {
    "F1": {
        "issue": 459,
        "frref": "FR-UIKIT-1/4",
        "title": "Vendor the kit Foundation (glass + tokens + house themes + slots) into the front door",
        "paths": "workspace/static/style.css + js/appkitGlass.js + css/kit-themes.css",
        "rationale": "The glass/token/theme/slots foundation the other kits render against.",
        "baseline": ("file_exists", "style.css"),
        "target": ("file_exists", "js/appkitGlass.js"),
    },
    "F2": {
        "issue": 460,
        "frref": "FR-UIKIT-1",
        "title": "Vendor the atomic Elements kit (.ow-btn/field/check/radio/switch/select/slider)",
        "paths": "workspace/static/js/appkitElements.js",
        "rationale": "One atomic-control vocabulary to replace bespoke .cal-btn sizing.",
        "baseline": ("file_exists", "style.css"),
        "target": ("file_exists", "js/appkitElements.js"),
    },
    "F3": {
        "issue": 461,
        "frref": "FR-UIKIT-1/3/5",
        "title": "Vendor the Window kit (.ow-window) and reconcile it with windowDrag/modalManager",
        "paths": "workspace/static/js/appkitWindow.js (reconcile modalManager.js/modalSnap.js/windowDrag.js)",
        "rationale": "One window mechanism, not two; modal a11y preserved.",
        "baseline": ("file_exists", "js/modalManager.js"),
        "target": ("file_exists", "js/appkitWindow.js"),
    },
    "F4": {
        "issue": 462,
        "frref": "FR-UIKIT-1/3",
        "title": "Vendor the Notice kit (.on-card) and re-back ui.js showToast through it",
        "paths": "workspace/static/js/appkitNotice.js (re-back ui.js showToast)",
        "rationale": "One notification mechanism; showToast keeps its signature.",
        "baseline": ("file_contains", "js/ui.js", "showToast"),
        # The re-back has LANDED: ui.js's toast composes the kit's notice chrome (it touches the
        # AppkitNoticeKit seam + carries the `.on-card` class). Probing the kit seam reference in
        # ui.js (not just the vendored module's existence) makes this a real regression gate for
        # the showToast re-back, not merely "the file was vendored". #462.
        "target": ("file_contains", "js/ui.js", "AppkitNoticeKit"),
    },
    "F5": {
        "issue": 463,
        "frref": "FR-UIKIT-1",
        "title": "Vendor the Gadget kit (.og-card + gadget rail)",
        "paths": "workspace/static/js/appkitGadget.js + appkitGadgetRail.js",
        "rationale": "One focusable widget-card primitive for the card-collection surfaces.",
        "baseline": ("file_exists", "js/applicantPortal.js"),
        "target": ("file_exists", "js/appkitGadget.js"),
    },
    "F6": {
        "issue": 464,
        "frref": "FR-UIKIT-1",
        "title": "Vendor the Decision kit (.odec-* prompt -> options -> confirm, risk variant)",
        "paths": "workspace/static/js/appkitDecision.js",
        "rationale": "Standardize approve/decline/confirm incl. the destructive variant.",
        "baseline": ("file_exists", "js/documentLibrary.js"),
        "target": ("file_exists", "js/appkitDecision.js"),
    },
    "F7": {
        "issue": 465,
        "frref": "FR-UIKIT-1",
        "title": "Vendor the Chat Hint kit (above-composer guide tip)",
        "paths": "workspace/static/js/appkitChatHint.js",
        "rationale": "One consistent above-composer guidance affordance.",
        "baseline": ("file_exists", "js/applicantChat.js"),
        "target": ("file_exists", "js/appkitChatHint.js"),
    },
}

# Cross-cutting.
_CROSS = {
    "X1": {
        "issue": 466,
        "frref": "FR-UIKIT-4",
        "title": "White-label the vendored kit — rename upstream codenamed modules to appkit*, keep the CI denylist green",
        "paths": ".github/workflows/ci.yml denylist + workspace/static/js/appkit*.js",
        "rationale": "Shipped artifacts carry no upstream codename; appkit* modules present.",
        "baseline": ("ci_contains", "denylist"),
        "target": ("file_exists", "js/appkitWindow.js"),
    },
    "X2": {
        "issue": 467,
        "frref": "FR-UIKIT-5",
        "title": "Kit components preserve the a11y affordances won in #379-#394",
        "paths": "workspace/static/js/appkitWindow.js (focus trap / Escape / dialog ARIA)",
        "rationale": "Re-skinning must not drop focus-trap/Escape/ARIA/reduced-motion.",
        "baseline": ("file_exists", "js/modalManager.js"),
        "target": ("file_contains", "js/appkitWindow.js", "aria-modal"),
    },
    "X3": {
        "issue": 468,
        "frref": "FR-UIKIT-7",
        "title": "Vendored kit modules pass node --check with no bundler and respect the style.css budget",
        "paths": ".github/workflows/ci.yml node --check + workspace/static/js/appkit*.js",
        "rationale": "Plain ES modules, no build step, additive CSS within the #398 budget.",
        "baseline": ("ci_contains", "node --check"),
        "target": ("file_exists", "js/appkitElements.js"),
    },
    "X4": {
        "issue": 469,
        "frref": "FR-UIKIT-8",
        "title": "Expose the kit house themes (theme-frosted / glass-full) in Settings via mountSettingsStep",
        "paths": "workspace/static/js/settings.js + css/kit-themes.css",
        "rationale": "Theme selection reachable in Settings, reusing mountSettingsStep.",
        "baseline": ("file_exists", "js/settings.js"),
        "target": ("file_exists", "css/kit-themes.css"),
    },
}

# Surfaces — map every visible surface onto its kit(s).
_SURFACES = {
    "S1": {
        "issue": 470,
        "frref": "FR-UIKIT-2",
        "title": "Map the global shell (nav / sidebar / rail / modals / toasts) onto Foundation + Window + Notice",
        "paths": "workspace/static/index.html, login.html, landing.html, modalManager.js, ui.js",
        "rationale": "The shell sets the visual baseline every nested surface inherits.",
        "baseline": ("file_exists", "index.html"),
        "target": ("css_contains", "--ow-"),
    },
    "S2": {
        "issue": 471,
        "frref": "FR-UIKIT-2",
        "title": "Map the OOBE onboarding wizard onto Window (modal) + Elements + Slots + Decision",
        "paths": "workspace/static/js/applicantOnboarding.js",
        "rationale": "The blocking wizard renders as a kit modal; focus-trap preserved.",
        "baseline": ("file_exists", "js/applicantOnboarding.js"),
        "target": ("file_contains", "js/applicantOnboarding.js", "ow-window"),
    },
    "S3": {
        "issue": 472,
        "frref": "FR-UIKIT-2",
        "title": "Map the Pending-Actions Portal + notification center onto Gadget + Notice + Decision",
        "paths": "workspace/static/js/applicantPortal.js",
        "rationale": "Items are gadget cards; notifications notice cards; actions decisions.",
        "baseline": ("file_exists", "js/applicantPortal.js"),
        "target": ("file_contains", "js/applicantPortal.js", "og-card"),
    },
    "S4": {
        "issue": 473,
        "frref": "FR-UIKIT-2",
        "title": "Map the Documents / resume redline review onto Window + Elements + Decision",
        "paths": "workspace/static/js/documentLibrary.js",
        "rationale": "Redline approve/decline renders through the Decision kit.",
        "baseline": ("file_exists", "js/documentLibrary.js"),
        "target": ("file_contains", "js/documentLibrary.js", "odec-"),
    },
    "S5": {
        "issue": 474,
        "frref": "FR-UIKIT-2",
        "title": "Map the criteria editor onto Elements + Gadget",
        "paths": "workspace/static/index.html (search-criteria block)",
        "rationale": "Bare labels/inputs migrate to associated-label Elements fields.",
        "baseline": ("file_contains", "index.html", "applicant-crit-titles"),
        "target": ("file_contains", "index.html", "ow-field"),
    },
    "S6": {
        "issue": 475,
        "frref": "FR-UIKIT-2",
        "title": "Map the attribute-cloud editor onto Elements + Gadget",
        "paths": "workspace/static/index.html (attribute block)",
        "rationale": "Attribute fields/switches adopt Elements; groups become gadget cards.",
        "baseline": ("file_contains", "index.html", "applicant-attr-name"),
        "target": ("file_contains", "index.html", "ow-switch"),
    },
    "S7": {
        "issue": 476,
        "frref": "FR-UIKIT-2",
        "title": "Map the Chat / assistant surface onto Chat Hint + Elements",
        "paths": "workspace/static/js/applicantChat.js",
        "rationale": "Above-composer guidance via the Chat Hint kit; Elements controls.",
        "baseline": ("file_exists", "js/applicantChat.js"),
        "target": ("file_contains", "js/applicantChat.js", "appkitChatHint"),
    },
    "S8": {
        "issue": 477,
        "frref": "FR-UIKIT-2",
        "title": "Map the Mind surface (remembers / playbooks / curation) onto Gadget + Decision",
        "paths": "workspace/static/js/applicantMind.js",
        "rationale": "Memories/playbooks are gadget cards; curation approvals are decisions.",
        "baseline": ("file_exists", "js/applicantMind.js"),
        "target": ("file_contains", "js/applicantMind.js", "og-card"),
    },
    "S9": {
        "issue": 478,
        "frref": "FR-UIKIT-2/9",
        "title": "Map the in-app Email / digest panel onto Notice + Gadget (the digest email stays exempt)",
        "paths": "workspace/static/js/emailLibrary.js (in-app panel only; FR-DIG-2)",
        "rationale": "In-app digest panel adopts the kit; the email artifact is untouched.",
        "baseline": ("file_exists", "js/emailLibrary.js"),
        "target": ("file_contains", "js/emailLibrary.js", "on-card"),
    },
    "S10": {
        "issue": 479,
        "frref": "FR-UIKIT-2",
        "title": "Map the Activity + Debug surface onto Gadget + Window",
        "paths": "workspace/static/js/applicantActivity.js, applicantDebug.js",
        "rationale": "Observability panels are gadget cards; the viewer is a kit window.",
        "baseline": ("file_exists", "js/applicantActivity.js"),
        "target": ("file_contains", "js/applicantActivity.js", "og-card"),
    },
    "S11": {
        "issue": 480,
        "frref": "FR-UIKIT-2",
        "title": "Map the Run controls / ops / Update surface onto Decision + Elements",
        "paths": "workspace/static/js/applicantUpdate.js",
        "rationale": "Operator controls via Elements; confirmable ops via the Decision kit.",
        "baseline": ("file_exists", "js/applicantUpdate.js"),
        "target": ("file_contains", "js/applicantUpdate.js", "odec-"),
    },
    "S12": {
        "issue": 481,
        "frref": "FR-UIKIT-2",
        "title": "Map the Live remote view / takeover onto Window + Decision",
        "paths": "workspace/static/js/applicantRemote.js",
        "rationale": "Responsive kit window (no 480px cap) + Decision risk-variant authorize.",
        "baseline": ("file_exists", "js/applicantRemote.js"),
        "target": ("file_contains", "js/applicantRemote.js", "ow-window"),
    },
    "S13": {
        "issue": 482,
        "frref": "FR-UIKIT-2",
        "title": "Map the Credential vault onto Elements + Window",
        "paths": "workspace/static/js/applicantVault.js",
        "rationale": "Masked Elements fields + a Window-kit add/edit modal.",
        "baseline": ("file_exists", "js/applicantVault.js"),
        "target": ("file_contains", "js/applicantVault.js", "ow-field"),
    },
    "S14": {
        "issue": 483,
        "frref": "FR-UIKIT-2",
        "title": "Map the Settings surface onto Elements + Window (reusing mountSettingsStep)",
        "paths": "workspace/static/js/settings.js",
        "rationale": "Settings controls adopt Elements; step panels adopt kit chrome.",
        "baseline": ("file_exists", "js/settings.js"),
        "target": ("file_contains", "js/settings.js", "ow-btn"),
    },
    "S15": {
        "issue": 484,
        "frref": "FR-UIKIT-2",
        "title": "Map the Connect-a-model / model ladder onto Elements + Gadget",
        "paths": "workspace/static/js/applicantModelLadder.js, modelPicker.js",
        "rationale": "Ladder tiers as drag-to-rank gadget cards; Elements endpoint form.",
        "baseline": ("file_exists", "js/applicantModelLadder.js"),
        "target": ("file_contains", "js/applicantModelLadder.js", "og-card"),
    },
    "S16": {
        "issue": 485,
        "frref": "FR-UIKIT-2",
        "title": "Map the Research surface onto the Gadget kit",
        "paths": "workspace/static/js/researchSynapse.js",
        "rationale": "Findings/sources render as gadget cards.",
        "baseline": ("file_exists", "js/researchSynapse.js"),
        "target": ("file_contains", "js/researchSynapse.js", "og-card"),
    },
    "S17": {
        "issue": 486,
        "frref": "FR-UIKIT-2/6",
        "title": "Map the Compare surface onto Elements in its themed-but-disabled state",
        "paths": "workspace/src/applicant_features.py (compare; present-but-disabled)",
        "rationale": "Compare looks like the product while staying disabled (kit covers disabled).",
        "baseline": ("section_present_but_disabled", "compare"),
        "target": ("file_exists", "js/appkitElements.js"),
    },
}

ITEMS: dict[str, dict] = {**_FOUNDATION, **_CROSS, **_SURFACES}
