# Issue #294 — Memory bridge as default + two-way learning — factory.py + app/config.py
# The bridge adapters exist and the curation-approval staging ships (GREEN). The feature
# wants MIND_BACKEND=bridge to be the production default (so the two-way learning loop is
# live without configuration) and learned attributes written back as provenanced entities.
# The @pending scenarios probe the default and the write-back-with-provenance seam.

Feature: Memory bridge as the default, two-way learning loop

  Scenario: A staged proposal is not written until it is approved
    Given the assistant tool belt with memory available
    When the assistant proposes remembering a note
    Then the proposal is staged for approval rather than written silently

  @pending
  Scenario: The bridge backend is the production default
    Given the engine default configuration
    When the configured memory backend is read
    Then it is the bridge so the learning loop is two-way by default

  @pending
  Scenario: A learned attribute is stored with provenance
    Given the engine has learned an attribute from past applications
    When the attribute is written to memory
    Then it is stored as an entity carrying its provenance and confidence
