# Issue #335 — src/applicant/adapters/browser/page_source.py (_safe_teardown lines 559-589; launch failure 481-483/532-534)
# Requirement: The engine's `_safe_teardown()` MUST emit a diagnostic (a logger warning)
# when a browser teardown step fails, instead of swallowing it with `except Exception: pass`,
# so an orphaned context / leaked process / CDP disconnect is visible — and a teardown
# failure during launch-failure cleanup never masks the original launch error.
# GREEN: teardown is best-effort and idempotent — calling it on a partially-built / empty
# driver never raises (getattr defaults keep it safe). @pending: teardown failures are
# silently discarded — there is no warning, so a teardown error during launch-failure
# cleanup hides the root cause in the logs.

Feature: Browser teardown failures surface a diagnostic instead of masking the root cause

  Scenario: Teardown on a partially-built driver never raises
    Given an engine page-source driver that never finished launching
    When best-effort teardown runs
    Then it completes without raising rather than crashing cleanup

  Scenario: A failing teardown step is logged as a warning rather than swallowed
    Given an engine page-source driver whose close step raises during teardown
    When best-effort teardown runs
    Then a warning naming the teardown failure is logged rather than silently discarded
