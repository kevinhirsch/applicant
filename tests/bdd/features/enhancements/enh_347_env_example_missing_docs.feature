# Issue #347 — .env.example (config template missing several documented vars)
# Requirement: .env.example MUST document SECURE_COOKIES, MAX_UPLOAD_SIZE,
# APPLICANT_UPDATE_ENABLED, MIND_BACKEND, SANDBOX_CONCURRENCY, and
# ALLOW_AUTOMATED_ACCOUNTS so operators discover every important setting from the template.
Feature: Environment template documents the audited config vars

  # GREEN — MIND_BACKEND is already documented in the template today.
  Scenario: The memory-backend selector is already documented
    Given the environment template
    When its documented settings are inspected
    Then the memory-backend selector is present

  # PENDING — the rest of the audited vars are still undocumented.
  Scenario: The secure-cookie and upload-size settings are documented
    Given the environment template
    When its documented settings are inspected
    Then the secure-cookie and upload-size settings are present

  Scenario: The sandbox-concurrency and automated-accounts settings are documented
    Given the environment template
    When its documented settings are inspected
    Then the sandbox-concurrency and automated-accounts settings are present

  Scenario: The in-UI update toggle is documented
    Given the environment template
    When its documented settings are inspected
    Then the in-UI update toggle is present
