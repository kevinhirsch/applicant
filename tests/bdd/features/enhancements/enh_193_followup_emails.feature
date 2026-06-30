# Issue #193 — No automated follow-up emails (thank-you / check-in) — FR-LOG-4
# Outbound notification infrastructure (Apprise) exists, but there is no follow-up
# generation, no reminder scheduling, and no detection that follow-up is warranted.
# PENDING — the follow-up seam does not exist.

Feature: Follow-up outreach is generated after submission

  Scenario: A thank-you follow-up is generated for a submitted application
    Given an application that was recently submitted
    When the follow-up service drafts outreach for it
    Then a follow-up message is produced for review

  Scenario: Follow-up is detected as warranted based on time since submission
    Given an application submitted long enough ago to warrant a check-in
    When the follow-up service evaluates whether outreach is due
    Then it reports that a follow-up is warranted
