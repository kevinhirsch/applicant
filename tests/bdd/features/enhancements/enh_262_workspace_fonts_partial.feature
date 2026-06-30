# Issue #262 — of 7 workspace font files, the stylesheet declares only the 3 FiraCode
# The main stylesheet (style.css) declares @font-face only for the FiraCode variants.
# The Inter faces are declared in the served shell (static/index.html), not style.css,
# so they DO load (corrects the audit's "never declared"). GohuFont.ttf has zero
# references anywhere and is the one genuinely dead file. GREEN: FiraCode is declared in
# the stylesheet, GohuFont is unreferenced, and the dead GohuFont file has been removed.

Feature: The stylesheet only ships font faces it actually uses

  Scenario: The stylesheet declares the FiraCode faces it loads
    Given the workspace main stylesheet
    Then it declares a font face for each FiraCode file it ships

  Scenario: The bitmap font file is referenced by nothing
    Given the workspace source tree
    When the tree is scanned for any reference to the bitmap font file
    Then nothing references it

  Scenario: The unreferenced bitmap font file has been removed
    Given the workspace font directory
    Then the unreferenced bitmap font file no longer exists
