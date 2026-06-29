# Issue #326 — workspace/src/bg_jobs.py (lines 59, 160)
# Requirement: The front-door background-job loader MUST emit a diagnostic (a logger
# warning) when the on-disk job-state file is corrupt, instead of silently resetting the
# queue to empty via `except Exception: pass`, so losing all scheduled background work is
# never invisible.
# `_load()` wraps `json.loads()` of the job store in bare `except Exception: pass`. GREEN:
# a corrupt store resets to an empty dict so the loader never crashes the monitor.
# @pending: the reset is silent — no warning is logged and no backup of the corrupt file
# is kept, so every scheduled background job vanishes with zero indication.

Feature: Corrupt background-job state surfaces a diagnostic instead of silent reset

  Scenario: A corrupt job-state file resets the queue to empty rather than crashing
    Given the front-door background-job store with a corrupt state file
    When the job store is loaded
    Then an empty job map is returned so the monitor keeps running

  @pending
  Scenario: A corrupt job-state file is logged before the queue is reset
    Given the front-door background-job store with a corrupt state file
    When the job store is loaded
    Then a warning naming the corrupt state file is logged rather than silently discarded
