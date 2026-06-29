# Issue #333 — workspace/src/*.py (systemic bare `except Exception:` across the source layer)
# Requirement: Every bare `except Exception:` block in the workspace source files MUST emit
# a diagnostic (no `except Exception: pass`); the worst file (builtin_actions.py) MUST have
# zero silent-swallow blocks. UMBRELLA tracking issue.
# Breakdown into per-file sub-issues: #323 (builtin_actions.py), #324 (agent_loop.py),
# #325 (ai_interaction.py), #326 (bg_jobs.py) — and the remaining offenders in the #333
# table still need individual audit. GREEN: an inventory assertion pins the current scale.
# @pending: the worst file (builtin_actions.py) has been remediated to zero silent-swallow
# blocks.

Feature: Workspace source files do not silently swallow errors

  Scenario: The source layer carries a large inventory of bare exception handlers today
    Given the workspace source files
    When the source files are scanned for bare exception handlers
    Then the source count of bare exception handlers is at least the audited baseline
    And many source handlers silently swallow the error with a bare pass

  @pending
  Scenario: The worst source file has no silent-swallow exception blocks
    Given the workspace source files
    When the worst source file is scanned for silent-swallow blocks
    Then the worst source file has zero exception handlers that swallow the error with a bare pass
