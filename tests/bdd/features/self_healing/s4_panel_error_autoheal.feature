# Slice S4 — Panel-error auto-heal. docs/stories/self-healing.md#s4-panel-error-auto-heal
# Grounds: scripts/monkey_crawl.py (console/pageerror/requestfailed/HTTP>=400/RENDER_ERR
# detection — today offline-only, see the story doc's Gap 4).
#
# Scope note (see docs/adr/0008-autonomous-self-healing.md Consequences and the story doc's
# Gap 5): a JS logic bug requires a code change + redeploy, which this slice's remediator
# cannot perform. Scope here is detect + audit + safe mitigation (disable the one broken
# gadget) + alert — never a claimed "fix" of code.
#
# NOT YET WIRED — see epic_self_healing.feature header for the collection/@pending convention.

Feature: Panel JS/Alpine errors self-heal within their real limits

  @pending
  Scenario: A live panel error is detected and audited
    Given a panel throws a console error or an uncaught exception in production
    When the live detector's next cycle runs
    Then a PanelErrorDetected event is emitted naming the panel and the error text
    And it is recorded in the audit trail

  @pending
  Scenario: A known regression is safely mitigated
    Given a panel error matches a previously-fixed regression class
    When it is detected again
    Then the remediator disables or reloads only the affected gadget
    And the rest of the panel remains usable
    And an alert is raised because a code-level regression requires a human-authored fix

  @pending
  Scenario: The remediator never claims to fix what requires a code change
    Given a panel error is a genuine code-level bug, not config, not data
    When the remediator cannot resolve it through a bounded operational action
    Then it fails safe — it audits and alerts
    And it does not report the error as resolved
