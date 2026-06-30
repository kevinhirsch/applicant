Feature: A posting is risk-checked for scam / ghost-job signals before applying
  # Issue #367 — new core rule: core/rules/posting_risk.py (does not exist yet)
  # Requirement: Before pre-fill/apply, the engine MUST score a posting for scam /
  # ghost-job risk (unrealistic comp, PII-harvesting fields, off-platform contact,
  # mismatched company domain) and MUST hold high-risk postings for explicit human
  # confirmation rather than auto-apply, so the user's PII is never blasted at a fake
  # listing. This is an entirely new capability (0 code today) — both scenarios are
  # @pending and probe the intended core seam.

  Scenario: A posting with scam signals is held for human confirmation
    Given a posting carrying scam / ghost-job signals
    When the posting-risk rule scores it before apply
    Then it is flagged high-risk and routed to human confirmation instead of auto-apply

  Scenario: A clean posting passes the risk check unchanged
    Given an ordinary posting with no scam signals
    When the posting-risk rule scores it before apply
    Then it is cleared and the apply flow proceeds unchanged
