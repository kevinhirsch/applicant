Feature: Build-time remote fetches are integrity verified
  # Issue #164 — docker/webtop-*/Dockerfile Google Chrome apt setup
  # The Google signing key is fetched and dearmored without verifying a known fingerprint or
  # checksum, and the apt source line uses plaintext http://. Neither a checksum-verify step nor
  # an https:// source line is present yet → @pending probes on the Dockerfile build step.

  Scenario: The Chrome apt source uses HTTPS
    Given the takeover desktop Dockerfile build step
    When the Google Chrome apt source line is inspected
    Then the apt source URL uses HTTPS

  Scenario: The fetched signing key is integrity verified
    Given the takeover desktop Dockerfile build step
    When the Google signing-key fetch is inspected
    Then the fetched key is verified against a pinned fingerprint or checksum
