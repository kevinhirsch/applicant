# Issue #303 — Remove: Notes integration with Applicant (explicitly descoped)
# Notes-to-Applicant wiring is descoped. The acceptance criterion is ABSENCE: there is no
# Applicant notes proxy route, the Notes surface is not in the Applicant section registry,
# and the engine's internal callback channel serves no notes lane. The general workspace
# Notes feature stays available; it is just not part of the Applicant product scope. These
# are GREEN today because the coupling is already absent.

Feature: Notes integration with Applicant is descoped and absent

  Scenario: There is no Applicant notes proxy route file
    Given the front-door route directory
    When the Applicant route files are listed
    Then there is no Applicant notes route file

  Scenario: Notes is not an Applicant feature section
    Given the Applicant feature-state layer
    When the Applicant section registry is inspected
    Then there is no notes section in the registry

  Scenario: The engine internal callback channel serves no notes lane
    Given the front-door internal callback routes
    When the internal routes are inspected
    Then no internal notes lane is exposed
