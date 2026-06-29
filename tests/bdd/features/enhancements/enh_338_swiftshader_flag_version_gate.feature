# Issue #338 — adapters/browser/page_source.py:_STEALTH_ARGS (--enable-unsafe-swiftshader)
#   + adapters/browser/stealth.py:PINNED_CHROME_MAJOR (124).
#   --enable-unsafe-swiftshader was removed from Chromium in Chrome 125+; passing an
#   unrecognised flag can make newer Chrome exit, and is itself a stale-automation tell.
# Requirement: The Chrome launch args MUST NOT pass --enable-unsafe-swiftshader to a
#   Chrome major >= 125; the flag is added only when the resolved Chrome major < 125.
# Related existing issue: #215 (PINNED_CHROME_MAJOR stale at 124, pre-dating the removal).
# GREEN: the launch kwargs are pure and unit-testable; the pinned major is coherent today.
# PENDING: the SwiftShader flag is version-gated against the resolved Chrome major.

Feature: The SwiftShader launch flag is version-gated for newer Chrome

  Scenario: The launch kwargs thread the coherent fingerprint and channel
    Given the coherent Chrome fingerprint built from the pinned major
    When the browser launch kwargs are built
    Then the launch args carry the automation-control stealth flag

  @pending
  Scenario: The SwiftShader flag is omitted for Chrome 125 and newer
    Given a deployment whose installed Chrome major is 125 or newer
    When the browser launch args are built for that Chrome
    Then the unsafe-swiftshader flag is not passed to the newer Chrome
