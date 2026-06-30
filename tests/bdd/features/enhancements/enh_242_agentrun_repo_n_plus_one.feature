# Issue #242 — adapters/storage/repositories.py AgentRunRepo (latest / max_seq / prune_old)
# The in-memory AgentRunRepo computes latest()/max_seq()/prune_old() correctly — the
# behavioural contract IS GREEN. The SQL AgentRunRepo materializes the ENTIRE
# agent_runs table with .all() then sorts/maxes/slices in Python (a full table scan
# every 60s tick); it does not push ORDER BY ... LIMIT 1 / MAX(seq) / a single
# DELETE ... WHERE id IN (...) to the database → @pending.

  Feature: Agent-run housekeeping is bounded, not a full-table scan

  Scenario: latest returns the newest run by timestamp then sequence
    Given an in-memory agent-run repository with several runs
    Then latest returns the most recent run

  Scenario: max_seq returns the highest sequence number
    Given an in-memory agent-run repository with several runs
    Then max_seq returns the highest sequence

  Scenario: pruning keeps only the newest runs
    Given an in-memory agent-run repository with several runs
    When old runs are pruned keeping only the newest two
    Then only the two newest runs remain

  Scenario: The SQL repo fetches the latest run with a bounded query
    Given the SQL agent-run repository source
    Then latest pushes ordering and a single-row limit to the database
