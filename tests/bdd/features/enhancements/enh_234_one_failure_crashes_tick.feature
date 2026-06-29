Feature: One failed channel delivery does not abort the rest of the ladder advance
  # Issue #234 — adapters/notification/apprise_notifier.py _fire_due / advance — FR-NOTIF-2
  # _dispatch is called before rung.fired = True, so a raising dispatch (Discord/SMTP down)
  # correctly leaves the rung un-fired for retry — but the exception propagates uncaught
  # through _fire_due -> advance -> the scheduler's _advance_ladders, crashing the tick and
  # dropping every OTHER pending rung due that tick. advance should catch per-rung delivery
  # failures so one unreachable channel can't take down unrelated escalations.

  Scenario: A raising delivery on one notification does not lose another notification's due rung
    Given a notifier whose dispatch raises for one notification but succeeds for another
    When the ladder is advanced with both rungs due on the same tick
    Then the healthy notification's rung still fired despite the other one failing
