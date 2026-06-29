# Issue #258 — Orphan route audit: /api/applicant/email/* — workspace/routes/applicant_email_routes.py
# The audit flagged the email proxy route file as having zero JS consumers. On this
# branch that is no longer true: emailLibrary's applicantDigest module fetches
# /api/applicant/email/* and is mounted into the email surface. The GREEN scenarios
# pin that the proxy is mounted AND has a real front-end consumer, closing the orphan.

Feature: The Applicant email proxy routes have a real front-end consumer

  Scenario: The email proxy router is mounted on the front-door app
    Given the front-door application
    When the mounted routes are inspected
    Then a route under the Applicant email prefix is present

  Scenario: A JavaScript module fetches the email proxy paths
    Given the front-door static JavaScript
    When the email proxy prefix is searched for across the JS modules
    Then at least one module fetches the Applicant email prefix

  Scenario: The email digest consumer is loaded by the email surface
    Given the front-door static JavaScript
    When the email surface module is inspected
    Then it mounts the Applicant digest consumer module
