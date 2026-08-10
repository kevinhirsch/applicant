# Slice S3 — Scorer-degrade auto-heal / auto-rescore. docs/stories/self-healing.md#s3-scorer-degrade-auto-heal--auto-rescore
# Grounds: src/applicant/application/services/scoring_service.py (_persist_or_defer,
# _bump_transient_failures — SCORE-P0), src/applicant/application/services/agent_loop.py
# (_viable_count). Replays the live SCORE-P0 incident (docs/APPLICANT-BACKLOG.md).
#
# NOT YET WIRED — see epic_self_healing.feature header for the collection/@pending convention.

Feature: Scorer degrade-to-embeddings self-heals

  @pending
  Scenario: A systemic degrade pattern is diagnosed, not treated as isolated noise
    Given multiple postings degrade to the embedding fallback within the same scoring tick
    When the remediator observes the pattern
    Then it checks whether the LLM tier is actually down, not just one posting misbehaving
    And it records its diagnosis in the audit trail

  @pending
  Scenario: A recovered LLM triggers an automatic re-score sweep
    Given the LLM was unreachable and has since recovered
    When the remediator detects the recovery
    Then it triggers a bounded re-score sweep of postings still sitting at a degraded score
    And no human re-triggers the sweep

  @pending
  Scenario: Zero viable postings after a scoring sweep is treated as a self-heal target
    Given a scoring sweep leaves the campaign with zero viable postings
    When this is detected
    Then remediation runs
    And, assuming real viable roles exist in the backlog, viable_count is restored above zero
    And an audit trail records the detection and the recovery
