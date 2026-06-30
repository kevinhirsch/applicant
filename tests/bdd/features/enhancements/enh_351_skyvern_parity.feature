Feature: Skyvern parity — autonomous form-filling capability bridge
  # Issue #351 (epic) — capstone acceptance for closing every gap vs Skyvern
  # (AGPL → idea-only; re-implemented from MIT/Apache twins). Each dimension is
  # delivered by a sub-issue: vision+DOM #305, coverage/self-healing #306,
  # CAPTCHA #350. All @pending: this is the end-state the epic converges on.

  Scenario: The planner reads an arbitrary form from a vision + DOM snapshot
    Given a job-application form the engine has never seen before
    When the planner builds a semantic snapshot fusing the rendered page and the DOM
    Then it produces a typed plan for the form without a hardcoded page model

  Scenario: Per-ATS routines are induced so coverage grows with use
    Given a successful pre-fill on a given ATS
    When the engine induces a reusable routine from it
    Then the next application to that ATS is guided by the induced routine

  Scenario: A broken selector triggers a self-correcting re-plan
    Given a planned step whose target element is no longer present
    When the step fails
    Then the planner reflects on the failure and re-plans rather than aborting

  Scenario: CAPTCHA is handled through the solver port
    Given a CAPTCHA encountered during an application
    When the engine routes it through the CAPTCHA solver port
    Then it is avoided, solved, or handed off per the configured strategy
