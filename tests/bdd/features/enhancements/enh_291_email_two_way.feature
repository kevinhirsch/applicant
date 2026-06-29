# Issue #291 — Two-way Applicant email workflow — applicant_email_routes.py + engine notification path
# Outbound digest/feedback proxying ships (GREEN): the email proxy is mounted and has a
# JS consumer (#258/#287). The INBOUND direction is missing: nothing scans the mailbox for
# rejection patterns, interview invites, or follow-ups to feed the learning loop, and rich
# inline-action HTML digests are not generated. The @pending scenarios probe those seams.

Feature: Two-way Applicant email — outbound digests ship, inbound parsing is the gap

  Scenario: Outbound digest delivery is reachable through the email proxy
    Given the front-door application
    When the mounted routes are inspected
    Then a digest deliver path is present under the email prefix

  @pending
  Scenario: Inbound rejection emails are detected and mark the application rejected
    Given an inbox message matching a rejection pattern
    When the inbound email parser runs over it
    Then the matching application is marked rejected and fed to learning

  @pending
  Scenario: Inbound interview invites become pending actions
    Given an inbox message containing an interview scheduling request
    When the inbound email parser runs over it
    Then an interview pending action is created for the operator
