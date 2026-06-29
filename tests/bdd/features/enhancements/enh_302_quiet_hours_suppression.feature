Feature: Time-based quiet-hours suppression with per-channel and override controls
  # Issue #302 — adapters/notification/apprise_notifier.py quiet window — FR-NOTIF-5
  # The core time-window suppression ships: a [start,end) minute span, HH:MM precision,
  # midnight wrap, timezone localization, and a 24/7 override (always_on). The GREEN
  # scenarios pin those behaviours. The residual gaps from #302 — PER-CHANNEL quiet-hours
  # behaviour ("discord respects quiet hours, email anytime") and a "deliver now" force-flush
  # of queued-during-quiet notifications — are not built, so they are @pending probes.

  Scenario: An HH:MM quiet window that wraps midnight is evaluated to the minute
    Given a quiet-hours window from 22:30 to 07:15
    When the current minute is checked against the window across the night
    Then a time inside the window is quiet and a time outside it is not

  Scenario: A quiet window expressed in the user timezone is localized before comparison
    Given a quiet-hours window configured in a non-UTC timezone
    When a UTC instant that falls inside the local night is checked
    Then the instant is treated as inside the quiet window

  @pending
  Scenario: Quiet hours can be configured per channel so email still sends overnight
    Given a notifier with per-channel quiet-hours preferences
    When a normal notification fires during quiet hours
    Then Discord is held but the email channel still delivers overnight

  @pending
  Scenario: A deliver-now action flushes notifications queued during quiet hours
    Given notifications that were deferred because of an active quiet window
    When the user taps deliver now to force-send the queued notifications
    Then the deferred notifications are flushed to their channels immediately
