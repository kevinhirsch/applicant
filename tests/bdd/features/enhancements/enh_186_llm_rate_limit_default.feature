Feature: LLM rate limiting is wired but defaults to disabled
  # Issue #186 — app/config.py + capacity_service.py: LLM rate limiting defaults to 0
# LLM_RATE_LIMIT defaults to 0 (disabled), so the agent loop can make unbounded LLM
# calls in a single tick. GREEN: the rate-limit queue is real and is created when an
# operator sets a positive limit. PENDING: there is no conservative non-zero default
# (e.g. 30 req/min), so out of the box token spend is unprotected.

  Scenario: A configured LLM rate limit creates a limiter queue
    Given a positive LLM rate limit is configured
    When the capacity service is built
    Then a per-provider LLM limiter queue is created with that limit

  @pending
  Scenario: A fresh install ships with a conservative LLM rate limit
    Given default engine settings
    Then the LLM rate limit defaults to a conservative positive value rather than disabled
