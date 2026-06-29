# Issue #340 — adapters/browser/stealth.py:detect_chrome_major
#   The chrome-channel probe only tries google-chrome-stable / google-chrome / chrome,
#   so a container that ships Chrome as chromium / chromium-browser / google-chrome-beta
#   is missed and the major silently falls back to the stale pinned default.
# Requirement: detect_chrome_major MUST also probe chromium, chromium-browser, and
#   google-chrome-beta on the chrome channel so Chrome is found in diverse container
#   environments rather than falling back to the pinned default.
# Related existing issue: #215 (stale PINNED_CHROME_MAJOR fallback when the probe misses).
# GREEN: with no Chrome on PATH the probe returns None (the honest fallback signal).
# PENDING: the probe also tries the container/beta binary names.

Feature: The Chrome version probe finds Chrome under container binary names

  Scenario: With no Chrome binary on PATH the probe reports nothing
    Given a deployment where no Chrome binary is on PATH
    When the Chrome major is probed
    Then the probe reports that no Chrome was found

  @pending
  Scenario: The probe also tries container and beta Chrome binary names
    Given a container that ships Chrome only as a container binary name
    When the Chrome major is probed on the chrome channel
    Then the probe also tries the container and beta binary names
