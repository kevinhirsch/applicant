Feature: Applications to one employer are capped per time window
  # Issue #371 — campaign throughput cap ships (core/entities/campaign.py, #195);
  # a PER-COMPANY cap is new. Distinct from campaign throughput #195 and per-board pacing.
  # Requirement: The engine MUST enforce a configurable per-company application cap per
  # time window (conservative default), holding overflow for the next window or human
  # review, and the cap MUST reset per window. GREEN: the campaign-level throughput hard
  # cap is real and clamps requests. PENDING: nothing bounds volume at a single employer.

  Scenario: Campaign-level throughput is clamped to a hard cap
    Given a campaign throughput far above the allowed ceiling
    When the throughput is clamped
    Then the applied value never exceeds the campaign hard cap

  Scenario: Applications to one company beyond the cap in a window are held
    Given a per-company application cap for a window
    When more applications to the same company are attempted than the cap allows
    Then the overflow applications are held rather than sent

  Scenario: The per-company cap resets per window
    Given a company that hit its per-company cap in the previous window
    When a new window begins
    Then the per-company cap is reset so applications to that company are allowed again
