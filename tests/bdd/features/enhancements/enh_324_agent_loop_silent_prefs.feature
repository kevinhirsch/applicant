# Issue #324 — workspace/src/agent_loop.py (lines 617, 655, 782, 816, 856)
# Requirement: The front-door agent loop MUST emit a diagnostic (a logger warning) when
# preference loading fails inside the prompt-assembly path, instead of swallowing it with
# `except Exception: pass` and running with silently degraded state.
# The main agent loop wraps preference loading, skill recording, tool discovery and
# form-backed detection in bare `except Exception: pass`. GREEN: degradation is correct —
# a preference-load failure must not abort prompt assembly. @pending: the failure is
# silent — no warning is logged, so the agent runs with missing preferences unnoticed.

Feature: Agent-loop degradation surfaces a diagnostic instead of running blind

  Scenario: A preference-load failure does not abort prompt assembly
    Given the front-door agent loop preference loader
    When loading a user's preferences raises
    Then prompt assembly continues with a safe default rather than crashing

  Scenario: A preference-load failure is logged as a warning rather than swallowed
    Given the front-door agent loop preference loader
    When loading a user's preferences raises
    Then a warning naming the preference-load failure is logged rather than silently discarded
