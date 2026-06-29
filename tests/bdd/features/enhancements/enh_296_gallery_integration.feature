# Issue #296 — Gallery integration — Applicant screenshots/materials as gallery collections
# The engine captures pre-fill screenshots and renders resume variants, and the debug
# surface can show screenshots — that part ships. The feature wants those visual artifacts
# hosted in the workspace GALLERY as collections (per-campaign, side-by-side variants,
# submitted confirmations). There is no Applicant<->Gallery bridge today, so the probes
# are @pending.

Feature: Applicant screenshots and materials as gallery collections

  Scenario: There is no Applicant gallery-bridge route file yet
    Given the front-door route directory
    When the Applicant route files are listed
    Then there is no Applicant gallery route file

  @pending
  Scenario: Pre-fill screenshots are published as a gallery collection
    Given the engine captured pre-fill screenshots for a campaign
    When the gallery bridge runs
    Then a gallery collection holds the screenshots with application metadata

  @pending
  Scenario: Resume variants are viewable side by side in the gallery
    Given several resume variants for one application
    When the gallery compare view is opened for that application
    Then the variants are presented side by side
