Feature: Credential vault banks credentials both ways
  # master spec §3.21 / FR-VAULT-1/2/3, NFR-PRIV-1

  Scenario: Manual entry in the vault (preferred upfront)
    Given a campaign with no stored credentials for a Workday tenant
    When the user manually banks a credential set for the tenant
    Then the credential set is sealed and retrievable for that tenant
    And the tenant is listed among the campaign's credential tenants

  Scenario: Auto-capture from a human account-creation in the live session
    Given a campaign with no stored credentials for a Workday tenant
    When credentials entered during live account creation are auto-captured
    Then the credential set is sealed and retrievable for that tenant
    And the stored secret is never returned in plaintext logs
