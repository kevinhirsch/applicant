Feature: Stealth prerequisites ship + the browser patch is baked (EPIC STEALTH)
  As the operator of a fresh Applicant deploy
  I want a clean install to ship the stealth prerequisites and the a0 image to
  permanently bake the residential-escalation browser patch
  So that automation never leaks the home IP and a rebuild never wipes the patch.

  Background:
    Given the Applicant repository checkout

  Scenario: The a0 image bakes the residential-escalation browser patch
    When I inspect the a0 image build
    Then the three patched _browser files are copied onto the baked core plugin
    And the build asserts the escalation marker so a clobbered overlay fails loudly

  Scenario: The prod compose surfaces the residential-proxy defaults
    When I inspect the a0 service environment
    Then the residential-proxy escalation env vars are present with the residential defaults

  Scenario: Install and update run the shared stealth preflight
    When I inspect the install and update scripts
    Then both source and call the shared stealth preflight

  Scenario: The preflight passes when every stealth prerequisite is present
    Given a host with the WireGuard client installed and egress exiting the VPS
    When the stealth preflight runs
    Then it reports no home-IP leak and succeeds

  Scenario: The preflight warns loudly but proceeds when non-strict
    Given a host missing the WireGuard client
    When the stealth preflight runs in non-strict mode
    Then it loudly warns about the home-IP risk and still returns success

  Scenario: The preflight hard-aborts a strict deploy when a prerequisite is missing
    Given a host missing the WireGuard client
    When the stealth preflight runs in strict mode
    Then it fails and aborts the deploy

  Scenario: The preflight catches a home-IP leak before deploying
    Given a host whose egress IP is not the VPS
    When the stealth preflight runs in strict mode
    Then it flags a home-IP leak risk and aborts the deploy
