Feature: Discord-first escalation ladder with 30s hold and web pre-empt
  # master spec §10 (Discord-first with 30s hold and web pre-empt) — FR-NOTIF-2/3/5

  Scenario: A web-pre-emptable decision holds Discord then escalates to email
    Given a configured notifier driven by a deterministic clock
    When a web-pre-emptable approval is queued
    Then the in-app channel fires immediately and Discord is held
    When thirty seconds elapse and the ladder advances
    Then Discord has fired but email has not
    When the configurable email timeout elapses and the ladder advances
    Then email has fired

  Scenario: Verifiable web presence pre-empts the Discord push
    Given a configured notifier where the user is verifiably present in the web UI
    When a web-pre-emptable approval is queued and the hold elapses
    Then the in-app surface is used and Discord is not pushed

  Scenario: Acting on one channel expires the others
    Given a configured notifier driven by a deterministic clock
    When an approval is queued and the user acts on the web portal
    Then the decision is no longer pending on any channel

  Scenario: Errors surface immediately across every channel any hour
    Given a configured notifier during quiet hours
    When an immediate error notification is queued
    Then every configured channel fires at once
