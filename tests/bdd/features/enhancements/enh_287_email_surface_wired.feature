# Issue #287 — Email surface wiring — workspace/routes/applicant_email_routes.py + emailLibrary/applicantDigest.js
# Follow-up to #258: the audit said the Applicant email surface was dead because no JS
# called the digest/feedback/approve/decline proxy routes. On this branch the digest
# consumer fetches them and the email feature-section is in the registry. The GREEN
# scenarios pin outbound digest reachability; the @pending scenario probes the residual
# gap — inline approve/decline rendered in the workspace email client itself (#291).

Feature: The Applicant email/digest surface is wired front-to-back

  Scenario: The email feature section is registered in the front door
    Given the Applicant feature-state layer
    When the Applicant section registry is inspected
    Then an email section is present and not present-but-disabled

  Scenario: The digest approve and decline proxy routes are mounted
    Given the front-door application
    When the mounted routes are inspected
    Then approve and decline application paths are present under the email prefix

  @pending
  Scenario: Rich digest emails carry inline approve/decline that POST back
    Given a digest email rendered for the operator
    When the email is generated for delivery
    Then it embeds inline approve and decline controls that post back to the engine
