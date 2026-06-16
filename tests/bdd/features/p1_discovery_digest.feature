Feature: Discover postings and deliver the daily digest
  # master spec §10 (Master aggregator in wave one) — FR-DISC-1/2/3, FR-DIG-3/6, FR-AGENT-3

  Scenario: The master aggregator discovers and normalizes postings
    Given a campaign with engineering search criteria
    When discovery runs over the enabled offline sources
    Then normalized job postings are persisted for the campaign
    And every posting records which source yielded it

  Scenario: The digest lists viable roles with a why-suggested rationale
    Given discovered postings have been scored for viability
    When the daily digest is built
    Then each digest row carries a score and a why-suggested rationale

  Scenario: An empty day produces an explicit empty-day note
    Given a campaign with no discovered postings
    When the daily digest is built
    Then the digest is flagged empty with an empty-day note
