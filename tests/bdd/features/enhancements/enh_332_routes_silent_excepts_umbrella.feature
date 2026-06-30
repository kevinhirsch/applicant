# Issue #332 — workspace/routes/*.py (systemic bare `except Exception:` across 19 route files)
# Requirement: Every bare `except Exception:` block in the workspace route files MUST emit
# a diagnostic (no `except Exception: pass`); the highest-risk route (email_routes.py) MUST
# have zero silent-swallow blocks. UMBRELLA tracking issue.
# Breakdown into per-file sub-issues handled separately: #323 (builtin_actions),
# #324 (agent_loop), #325 (ai_interaction), #326 (bg_jobs) are the src/ analogues;
# this umbrella covers the routes/ layer. GREEN: an inventory assertion pins the current
# scale of the problem (hundreds of bare excepts, many silently swallowing). @pending: the
# chosen high-risk file (email_routes.py) has been remediated to zero silent-swallow blocks.

Feature: Workspace route files do not silently swallow errors

  Scenario: The route layer carries a large inventory of bare exception handlers today
    Given the workspace route source files
    When the route files are scanned for bare exception handlers
    Then the count of bare exception handlers is at least the audited baseline
    And few of them silently swallow the error with a bare pass after the G09 sweep

  Scenario: The highest-risk route file has no silent-swallow exception blocks
    Given the workspace route source files
    When the highest-risk route file is scanned for silent-swallow blocks
    Then it has zero exception handlers that swallow the error with a bare pass
