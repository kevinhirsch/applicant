Feature: A runnable end-to-end harness drives the whole pipeline to the stop-boundary
  # Issue #364 — core/rules/prefill_boundary.py (stop-boundary); no tests/e2e harness today
  # Requirement: A runnable end-to-end test MUST exercise the full pipeline (discovery →
  # scoring → digest → approval → tailoring → pre-fill) with fakes for the irreducible
  # external boundaries, from a seeded campaign to the stop-boundary, asserting a
  # human-review item is produced and no auto-submit occurs.
  #
  # The review-gate / stop-boundary core rule already ships, so the first two scenarios are
  # GREEN regression coverage. The assembled discovery→…→stop-boundary harness (a dedicated,
  # discoverable e2e entrypoint) does not exist yet and is @pending.

  Scenario: The stop-boundary refuses a final submit without explicit authorization
    Given the pre-fill stop-boundary rule
    When the engine attempts the final submit without authorization
    Then the action is refused so no auto-submit occurs

  Scenario: Ordinary pre-fill field steps are allowed up to the boundary
    Given the pre-fill stop-boundary rule
    When the engine attempts to fill an ordinary field
    Then the field-fill step is allowed

  Scenario: A seeded campaign runs end-to-end and stops at the human-review gate
    Given a seeded campaign and an assembled end-to-end pipeline harness
    When the harness runs discovery through pre-fill with faked external boundaries
    Then a scored digest and an approved-item tailoring are produced and the final submit is withheld for review
