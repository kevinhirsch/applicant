# Issue #192 — No ghosting/silence tracking (no SLA / time-since-submission) — FR-LOG-4
# Nothing tracks how long a submitted application has gone without a response, and there
# is no SLA threshold to flag likely-ghosted applications. PENDING — the seam is absent.

Feature: Submitted applications that go silent are flagged as likely ghosted

  @pending
  Scenario: Time since submission is tracked per application
    Given an application submitted some days ago with no response
    When the silence tracker evaluates it
    Then it reports the elapsed time since submission

  @pending
  Scenario: Silence past the SLA threshold flags the application as likely ghosted
    Given an application with no response well past the no-response threshold
    When the silence tracker evaluates it against the SLA
    Then the application is flagged as likely ghosted
