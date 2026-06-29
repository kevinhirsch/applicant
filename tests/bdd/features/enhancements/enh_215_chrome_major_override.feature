# Issue #215 — stealth fingerprint coherence / adapters/browser/stealth.py:PINNED_CHROME_MAJOR
# PINNED_CHROME_MAJOR is a stale hardcoded 124; in containers without Chrome on PATH the
# probe fails and falls back to 124, so the UA says Chrome/124 while real Chrome's Sec-CH-UA
# says a newer major — a detectable incoherence. GREEN: the derived fingerprint is
# internally coherent for the pinned major. @pending: an env-var override pins the major to
# the actually-installed Chrome.

Feature: The Chrome major can be pinned to the installed browser to stay coherent

  Scenario: The derived fingerprint is internally coherent
    Given the coherent Chrome fingerprint built from the pinned major
    When the fingerprint is checked for internal consistency
    Then the user-agent, platform and client hints all agree

  @pending
  Scenario: An environment override pins the Chrome major in a container
    Given a deployment where Chrome is not probeable on PATH
    When the Chrome major is resolved with an environment override set
    Then the override value is used instead of the stale pinned default
