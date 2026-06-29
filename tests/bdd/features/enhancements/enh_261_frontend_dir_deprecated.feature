# Issue #261 — the frontend/ directory is deprecated but still ships dead weight
# frontend/ is a migration-era shell. The white-labeled workspace front-door is the only
# public surface; workspace/app.py mounts only its own static/ directory and never
# references frontend/. frontend/ still carries fonts that are exact duplicates of the
# workspace fonts plus dozens of JS modules with no workspace counterpart. GREEN: prove
# the workspace does not serve frontend/ and that the fonts are byte-identical dupes.
# @pending: the cleanup acceptance criterion — the deprecated directory has been removed.

Feature: The deprecated migration shell is not part of the front door

  Scenario: The workspace app never serves the deprecated frontend directory
    Given the workspace application module
    Then it mounts only its own static directory
    And it never mounts or routes to the deprecated frontend directory

  Scenario: The frontend fonts are exact duplicates of the workspace fonts
    Given the deprecated frontend directory
    When its font files are compared with the workspace font files
    Then they are byte-identical duplicates

  Scenario: The frontend ships browser modules with no workspace counterpart
    Given the deprecated frontend directory
    Then it contains applicant modules that do not exist in the workspace

  @pending
  Scenario: The deprecated frontend directory has been removed
    Given the deprecated frontend directory
    Then the deprecated frontend directory no longer exists
