Feature: The REVIEW-UX + MODEL-CONFIG workstreams are wired into the live app
  # docs/APPLICANT-BACKLOG.md §EPIC REVIEW-UX + §EPIC MODEL-CONFIG (Integrate step)
  # The routers/toolbox/proxy built by the workstreams only take effect once they are
  # registered. These scenarios pin the integration seams end-to-end (no UI, no network).

  Scenario: The engine exposes the review workflow surface
    Given the application is built
    Then the review router is mounted at /api/review

  Scenario: The live campaign chat is offered the gated action tools
    Given a tool-capable campaign chat with the criteria and digest services it holds
    When the chat assembles its toolbox
    Then the toolbox offers edit_criteria, rescore, draft_application and discard_job

  Scenario: The review proxy translates a decision to the engine endpoint
    Given the review proxy is loaded
    When the panel decides to continue an application
    Then the proxy forwards a POST to the engine continue endpoint

  Scenario: A persisted smart-routing override wins over the environment default
    Given the environment default for smart routing is on
    When the operator has persisted an override turning it off
    Then the effective smart-routing decision is off
