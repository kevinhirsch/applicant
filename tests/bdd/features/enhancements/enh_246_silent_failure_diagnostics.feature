Feature: Material generation enforces truthfulness and surfaces silent degradation
  # Issue #246 — material_service.py has many bare `except Exception:` blocks (silent failure)
# Engine: application/services/material_service.py + core/rules/truthfulness.py. The
# generation pipeline silently degrades on failure at many layers; the worry is that the
# truthfulness post-check could be skipped if an earlier layer swallows an error. GREEN:
# the truthfulness guard itself is hard-enforced — assert_no_fabrication raises on an
# unsupported claim, and the deterministic fallback never fabricates. PENDING: there is
# no silent-exception counter / diagnostic event that surfaces when degradation crosses
# a threshold.

  Scenario: The fabrication guard raises on an unsupported claim
    Given a material service over the true candidate source
    When generated text claims a skill absent from that source
    Then the fabrication guard rejects it rather than degrading silently

  Scenario: The deterministic fallback reframes truthfully without fabricating
    Given a material service with no model wired
    When a variant is generated from a truthful source toward a job description
    Then the generated body adds no claim absent from the source

  @pending
  Scenario: Repeated silent degradation surfaces a diagnostic instead of vanishing
    Given a material service that counts silent degradations
    When silent failures cross the diagnostic threshold
    Then a diagnostic event is surfaced rather than producing empty output
