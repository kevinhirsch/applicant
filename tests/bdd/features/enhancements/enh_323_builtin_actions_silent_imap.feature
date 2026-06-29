# Issue #323 — workspace/src/builtin_actions.py (lines 774, 819, 971, 1048, 1199, 1765)
# Requirement: The front-door MUST emit a diagnostic (a logger warning) when an IMAP
# logout in builtin_actions silently fails, instead of swallowing it with `except Exception: pass`.
# The worst-risk workspace file mutes IMAP logout failures (connection leak) with bare
# `except Exception: pass`. GREEN: graceful degradation is correct today — a logout that
# raises does NOT crash the surrounding email task. @pending: the failure is silent —
# no warning is logged, so a leaking IMAP connection is invisible to operators.

Feature: IMAP logout failures in the front-door surface a diagnostic, not silence

  Scenario: A failing IMAP logout does not crash the surrounding email task
    Given the front-door builtin email actions module
    When an IMAP connection logout raises during cleanup
    Then the surrounding task continues rather than crashing

  @pending
  Scenario: A failing IMAP logout is logged as a warning rather than swallowed
    Given the front-door builtin email actions module
    When an IMAP connection logout raises during cleanup
    Then a warning naming the logout failure is logged rather than silently discarded
