Feature: The takeover desktop base image is pinned to an immutable digest
  # Issue #160 — docker/webtop-chrome/Dockerfile line 30 (supply-chain hardening)
  # The base image is pulled from a MUTABLE tag (lscr.io/linuxserver/webtop:ubuntu-cinnamon)
  # rather than a digest-pinned reference, so a rebuild can silently pull a different
  # upstream image. Pinning to @sha256:... is not yet done → @pending probe on the Dockerfile.

  @pending
  Scenario: The webtop base image default is digest pinned
    Given the takeover desktop Dockerfile
    When its default base image reference is inspected
    Then the base image is pinned to an immutable digest
