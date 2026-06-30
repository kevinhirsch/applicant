Feature: The live-session iframe expands on small viewports
  # Issue #399 — workspace/static/js/applicantRemote.js:90 / :92 (height:42dvh;max-height:480px)
  # Requirement: The live-session iframe MUST use a viewport-relative height that expands on small/handheld viewports rather than being capped at a fixed 480px.

  Scenario: The live session is embedded with a viewport-relative height
    Given the live-session takeover browser module
    When the embedded session frame styling is inspected
    Then the frame height is expressed in viewport-relative units

  Scenario: The frame is not letterboxed by a fixed 480px cap on mobile
    Given the live-session takeover browser module
    When the embedded session frame styling is inspected
    Then the frame is not pinned to a fixed 480px maximum height
