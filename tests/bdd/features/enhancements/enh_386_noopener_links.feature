Feature: New-tab links are protected against reverse tabnabbing
  # Issue #386 — workspace/static/js/admin.js:1336,1640; settings.js:4205; landing.html:322,349,565
  # Requirement: Every target="_blank" anchor MUST include rel="noopener"
  # (rel="noopener noreferrer" for external destinations).
  #
  # GREEN regression: most modules are already correct (e.g. settings.js carries
  # rel="noopener noreferrer" on its new-tab links). The @pending scenarios probe the
  # named stragglers that still open new tabs without rel="noopener" today.

  Scenario: An already-hardened module guards every new-tab link
    Given a front-door module that already hardens its new-tab links
    When its new-tab anchors are inspected
    Then every new-tab anchor in that module carries a noopener relationship

  @pending
  Scenario: The admin OAuth-authorize links guard the opener reference
    Given the admin console module
    When its new-tab anchors are inspected
    Then every new-tab anchor in that module carries a noopener relationship

  @pending
  Scenario: The settings OAuth-authorize link guards the opener reference
    Given the settings module OAuth-authorize new-tab link
    When that new-tab anchor is inspected
    Then that new-tab anchor carries a noopener relationship

  @pending
  Scenario: The landing-page external links guard the opener reference
    Given the landing page
    When its new-tab anchors are inspected
    Then every new-tab anchor on the landing page carries a noopener relationship
