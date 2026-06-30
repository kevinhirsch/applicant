# Issue #254 — workspace/services/faces/ package is entirely dead
# services/faces/__init__.py ("Face detection + embedding service") is never imported by
# any Python file in the workspace. Cleanup shipped.

Feature: The unused face-detection package is not shipped

  Scenario: Nothing in the workspace imports the face package
    Given the workspace source tree
    When every Python file is scanned for an import of the face package
    Then no file imports it

  Scenario: The dead face package has been removed
    Given the workspace source tree
    Then the face package directory no longer exists
