# Issue #256 — Inter woff2 files allegedly never loaded; GohuFont.ttf unreferenced
# Investigation correction: the three Inter woff2 files ARE loaded — the served
# workspace shell (static/index.html) declares @font-face for the 'Inter' family that
# the CSS font stacks reference, so the browser fetches them. They are NOT dead.
# What IS dead is static/fonts/custom/GohuFont.ttf, which has zero references anywhere.
# GREEN: the Inter faces are declared in the served shell, and the genuinely
# unreferenced GohuFont bitmap file has now been removed.

Feature: Shipped font files are actually loaded by the served shell

  Scenario: The served shell declares the Inter font faces that the styles reference
    Given the served workspace shell and its styles
    Then the Inter font family is declared with a face for each shipped Inter file
    And the Inter family is named in the CSS font stacks

  Scenario: The unreferenced bitmap font file has been removed
    Given the workspace font directory
    Then the unreferenced bitmap font file no longer exists
