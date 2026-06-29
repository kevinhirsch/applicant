Feature: The notification delivery state machine is guarded against concurrent access
  # Issue #235 — adapters/notification/apprise_notifier.py _sent dict — FR-NOTIF-2/3
  # The central _sent dict is read and mutated by notify/expire/advance/_fire_due across
  # both the scheduler worker thread and the API event loop, with no lock. The service
  # already added a lock only for the digest-ready marker. The _sent dict needs the same
  # protection so an expire racing a _fire_due cannot fire an already-handled decision a
  # second time. @pending probes for the absent lock on the notifier.

  @pending
  Scenario: The notifier holds a lock around its shared delivery state
    Given the shipped notifier adapter
    When the delivery state machine is inspected for a concurrency guard
    Then a lock protects the shared sent-delivery dictionary
