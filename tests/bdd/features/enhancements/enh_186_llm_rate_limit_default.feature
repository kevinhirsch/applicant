Feature: LLM rate limiting is wired but defaults to disabled
  # Issue #186 — app/config.py + capacity_service.py: LLM rate limiting defaults to 0
# LLM_RATE_LIMIT now defaults to 30 (a conservative rate). GREEN: the rate-limit queue is real and is created with the default limit out of the box. The conservative default protects against runaway token spend.

  Scenario: A configured LLM rate limit creates a limiter queue
    Given a positive LLM rate limit is configured
    When the capacity service is built
    Then a per-provider LLM limiter queue is created with that limit

  Scenario: A fresh install ships with a conservative LLM rate limit
    Given default engine settings
    Then the LLM rate limit defaults to a conservative positive value rather than disabled
