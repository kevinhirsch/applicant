Feature: Quiet hours silence non-critical notifications instead of firing 24/7
  # Issue #172 — adapters/notification/apprise_notifier.py — FR-NOTIF-5
  # docs/open-items.md once listed quiet hours as deferred, but the adapter now ships a
  # real window: NORMAL approvals/digests defer on the Discord/email rungs while inside
  # the configured quiet window, errors still fire any hour, and 24/7 mode disables it.
  # The GREEN scenarios pin the shipped suppression; the @pending scenario probes the
  # residual gap — a single typed "critical" urgency that overrides quiet hours even on
  # the Discord/email rungs (today the urgency enum only has NORMAL and IMMEDIATE).

  Scenario: A normal approval defers its Discord and email rungs during quiet hours
    Given a notifier configured with a quiet-hours window covering the current time
    When a normal approval is queued and the ladder is advanced past the email timeout
    Then neither Discord nor email has fired while inside the quiet window
    And the in-app surface still received the approval immediately

  Scenario: An error notification still fans out to every channel during quiet hours
    Given a notifier configured with a quiet-hours window covering the current time
    When an immediate error notification is queued
    Then every configured channel fired at once despite the quiet window

  Scenario: Twenty-four-seven mode disables the quiet window entirely
    Given a notifier configured for round-the-clock delivery with a quiet window
    When a normal approval is queued and the ladder is advanced past the email timeout
    Then Discord and email both fired even though a quiet window was configured

  Scenario: A critical action overrides quiet hours without being a generic error
    Given a notifier configured with a quiet-hours window covering the current time
    When a critical action is queued that must reach the user during quiet hours
    Then the critical action fires on Discord even inside the quiet window
