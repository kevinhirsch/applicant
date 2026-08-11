# EPIC AGENTS — docs/APPLICANT-BACKLOG.md; architecture in docs/adr/0009-self-improving-agents.md
# Story: docs/stories/self-improving-agents.md
# Extends: EPIC SELF-HEAL (docs/adr/0008-autonomous-self-healing.md) — see ADR-0009's "Relation
# to ADR-0008" section; this feature file covers EPIC AGENTS' own epic-wide guardrails only.
#
# NOT YET WIRED: no tests/bdd/steps/*.py module calls scenarios() on this file, so pytest-bdd
# does not collect it (see the story doc's "BDD framework + scaffold status" section). Every
# scenario below is @pending in anticipation of that wiring — when a step module is added, keep
# @pending until the corresponding slice (RC1-RC3, AE1-AE6, SH1, GATE-1,
# docs/stories/self-improving-agents.md) actually ships, then drop the tag scenario-by-scenario
# as behaviour lands (repo convention, see tests/bdd/conftest.py::pytest_bdd_apply_tag and
# tests/bdd/steps/test_enh_t12_cua_steps.py).

Feature: The product improves itself without a human tuning it or babysitting deploys

  @pending
  Scenario: The Automation Engineer never auto-submits a user's application
    Given any action the Automation Engineer takes, in development, canary, or production
    Then it never calls the final-approval submit path on the user's behalf
    And a user's application is only ever submitted by an explicit user decision or an explicit
      per-application auto-submit opt-in the user set themselves

  @pending
  Scenario: Neither agent ever destroys user data
    Given any action the Reflection Coach or the Automation Engineer takes
    Then no Application, JobPosting, credential, or document is ever deleted as a side effect
    And any data-affecting change the Automation Engineer ships is reversible by a snapshot taken
      before it was applied

  @pending
  Scenario: A global kill switch halts both agents immediately
    Given the global kill switch is engaged
    When the Reflection Coach's next evaluation cycle or the Automation Engineer's next pipeline
      stage would run
    Then it does not run
    And the halt is visible on the activity feed

  @pending
  Scenario: A single proposed action can be vetoed without killing everything else
    Given a specific action is pending on the shared backlog queue or the activity feed
    When the user vetoes that one action
    Then only that action is blocked
    And every other in-flight or queued action continues unaffected

  @pending
  Scenario: Every new piece of functionality is communicated proactively as it is built
    Given the Automation Engineer starts building a new capability
    When it begins the build (not after it ships)
    Then the user receives a proactive notification describing what is being built and why
    And the notification is visible on the activity feed with an audit entry

  @pending
  Scenario: A build is canaried before it is ever promoted to production
    Given the Automation Engineer has a change ready to ship
    When it attempts to promote the change
    Then it first deploys to the disposable e2e test instance
    And the full test suite and a browser monkey-crawl both pass against that instance
    And only then is the change promoted to production, with a pre-promotion snapshot taken
    And a failed post-promotion health check triggers an automatic rollback to that snapshot
