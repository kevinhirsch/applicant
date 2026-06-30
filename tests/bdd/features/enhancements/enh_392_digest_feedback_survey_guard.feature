Feature: Digest feedback and survey actions guard against re-entry
  # Issue #392 — workspace/static/js/emailLibrary/applicantDigest.js:552 (_onFeedback) / :726 (_onSurvey)
  # Requirement: _onFeedback and _onSurvey MUST guard re-entry while a prompt or submit is outstanding, matching the per-row Approve/Pass/Research guards.

  Scenario: The per-row actions already guard re-entry (the pattern to match)
    Given the Daily-updates digest browser module
    When the Approve, Pass and Research handlers are inspected
    Then each disables its control before awaiting the request

  Scenario: Sending feedback cannot be triggered twice while a prompt is open
    Given the Daily-updates digest browser module
    When the Send-feedback handler is inspected
    Then it guards re-entry while the prompt or submit is outstanding

  Scenario: The quick survey cannot be submitted twice
    Given the Daily-updates digest browser module
    When the Quick-survey handler is inspected
    Then it guards re-entry while the survey or submit is outstanding
