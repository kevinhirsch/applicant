# Issue #259 — Orphan route audit: /api/applicant/research/* — workspace/routes/applicant_research_routes.py
# The audit flagged the research proxy (POST /{campaign_id}/run, GET /{campaign_id}/budget)
# as having zero JS consumers. On this branch the applicantDigest module fetches
# /api/applicant/research/* to trigger a manual research run from a digest row. The GREEN
# scenarios pin the proxy mount + the engine-client methods + the JS consumer.

Feature: The Applicant research proxy routes have a real front-end consumer

  Scenario: The research proxy router is mounted with run and budget paths
    Given the front-door application
    When the mounted routes are inspected
    Then the research run and budget paths are present under the research prefix

  Scenario: A JavaScript module fetches the research proxy paths
    Given the front-door static JavaScript
    When the research proxy prefix is searched for across the JS modules
    Then at least one module fetches the Applicant research prefix

  Scenario: The engine client exposes research run and budget calls
    Given the front-door engine client
    When the engine client is inspected for research methods
    Then it exposes a research run call and a research budget call
