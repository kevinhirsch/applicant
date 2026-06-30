Feature: Urgent action alerts are pushed to the user's device via the ntfy channel
  # Issue #300 — adapters/notification (ntfy push) — FR-NOTIF-1 / new feature
  # The workspace stack already runs an ntfy service, but the engine notifier only knows
  # Discord, in-app, and email. This wires a push channel: CAPTCHA / verification / final
  # submit get a CRITICAL push with a deep link to the takeover session, digests get a
  # NORMAL push, and a per-channel preference can mute it. None of this ships yet, so both
  # scenarios are @pending and probe the intended seams (a push channel enum value / a push
  # configuration entrypoint on the adapter).

  Scenario: The notifier exposes a push channel for ntfy delivery
    Given the shipped notification channel set
    When the available channels are inspected for a device-push option
    Then a push channel is available alongside Discord, in-app, and email

  Scenario: An urgent takeover alert is dispatched to the push channel with a deep link
    Given a notifier configured with an ntfy push endpoint
    When a critical takeover alert with a deep link is queued
    Then the push channel received the alert carrying the takeover deep link
