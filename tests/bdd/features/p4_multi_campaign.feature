Feature: Multi-campaign isolation with shared mapping knowledge
  # master spec §10 ("multi-campaign isolation") — NFR-EXT-1, FR-CRIT-4, FR-ATTR-2, FR-LEARN-1

  Scenario: Two campaigns keep attribute values isolated but share field-mapping knowledge
    Given two campaigns A and B
    When each campaign stores its own value for the same attribute
    And a field mapping is learned once as shared cross-campaign knowledge
    Then each campaign resolves the shared mapping to its own value
    And only one global field mapping exists for that field

  Scenario: A conversion in one campaign biases only that campaign
    Given two campaigns A and B
    When campaign A records a real conversion
    Then campaign A's converting-role signature is learned
    And campaign B's converting-role signature stays empty
