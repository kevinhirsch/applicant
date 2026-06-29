# Issue #243 — adapters/storage/models.py (DiscoverySourceModel, OnboardingProfileModel)
# The InMemory adapter enforces uniqueness by keying DiscoverySource on
# (campaign_id, source_key) and OnboardingProfile on campaign_id. Some SQL models do
# carry the matching unique constraint (CredentialModel uq_credentials_campaign_tenant,
# ToolSettingModel.tool_key, AppConfigModel.key) — GREEN. But DiscoverySourceModel and
# OnboardingProfileModel declare NO unique constraint, so the SQL lane allows duplicate
# rows the InMemory lane forbids → @pending.

  Feature: SQL models carry the unique constraints the in-memory lane enforces

  Scenario: In-memory discovery sources are keyed uniquely per campaign and source
    Given an in-memory storage
    When the same discovery source key is upserted twice for one campaign
    Then only one discovery source exists for that key

  Scenario: Models that should be unique declare the constraint
    Given the SQL models
    Then the credentials model is unique per campaign and tenant
    And the tool-settings and app-config keys are unique

  @pending
  Scenario: The discovery-source model is unique per campaign and source key
    Given the SQL models
    Then the discovery-source model declares a campaign-and-source unique constraint

  @pending
  Scenario: The onboarding-profile model is unique per campaign
    Given the SQL models
    Then the onboarding-profile model declares a per-campaign unique constraint
