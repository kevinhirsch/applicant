Feature: A failed digest email send does not permanently consume its dedup key
  # Issue #233 — adapters/notification/apprise_notifier.py send_email — FR-DIG-2
  # send_email adds the dedup key to the sent-set BEFORE calling _dispatch. If the real
  # SMTP send raises, the key is already committed, so the retry sees the key and returns
  # True without ever delivering — the digest email for that campaign+day is lost. The
  # dedup key should be committed only AFTER a successful dispatch. GREEN pins the
  # idempotency that already works on the happy path; @pending probes the lost-on-failure
  # bug by failing the first dispatch and asserting a retry actually re-dispatches.

  Scenario: A repeated digest email with the same key is an idempotent no-op
    Given a notifier with an email channel and a deterministic clock
    When the same digest email is sent twice with one dedup key
    Then the email channel dispatched exactly once

  Scenario: A digest email is not lost when the first SMTP dispatch fails
    Given a notifier with an email channel whose first dispatch fails
    When the digest email is sent, fails, and is then retried
    Then the retry re-dispatches the email rather than silently returning sent
