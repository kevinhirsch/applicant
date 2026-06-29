Feature: Locked dependencies are at or above their advisory-fixed releases
  # Issue #162 — uv.lock (pypdf, pydantic-settings)
  # The advisory-flagged packages have been bumped on this branch: uv.lock now resolves
  # pypdf >= 6.14.2 and pydantic-settings >= 2.14.2. GREEN regression coverage that the
  # locked versions stay at or above the fixed releases.

  Scenario: The PDF library is at the advisory-fixed version
    Given the resolved dependency lockfile
    When the locked version of the PDF library is read
    Then it is at least the advisory-fixed PDF library release

  Scenario: The settings library is at the advisory-fixed version
    Given the resolved dependency lockfile
    When the locked version of the settings library is read
    Then it is at least the advisory-fixed settings library release
