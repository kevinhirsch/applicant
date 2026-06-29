# Issue #358 — MASTER TRACKING: remaining unaudited areas (editor JS, webtop
# Dockerfiles, uv.lock, workspace/requirements.txt, BDD step bodies, frontend/, etc.)
# Requirement: Every remaining unaudited area listed in this master tracker MUST be
# individually swept and recorded as audited; the tracker enumerates its child areas
# and stays open until each is cleared.
Feature: Master audit tracker for remaining unaudited areas

  # GREEN — the inventory the tracker is keyed to: the child areas still exist and
  # are still un-cleared today, so the tracker is correctly still open.
  Scenario: The webtop desktop Dockerfiles enumerated by the tracker still exist
    Given the repository tree
    When the webtop Dockerfiles are enumerated
    Then at least three webtop desktop Dockerfiles are present

  Scenario: The dependency lockfile the tracker flags for CVE scanning still exists
    Given the repository tree
    When the dependency lockfile is located
    Then the uv lockfile is present and substantial

  # PENDING — the audit completion this master tracker is opened to drive.
  @pending
  Scenario: Every remaining unaudited area has been swept and cleared
    Given the repository tree
    When the master audit ledger is consulted
    Then every enumerated unaudited area is recorded as audited
