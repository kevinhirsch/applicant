Feature: Engine callback access requires owner attribution
  # Issue #230 — workspace/app.py internal callback channel (around lines 261-266)
  # When the internal token matches but X-Applicant-Owner is unset/unknown, the request is
  # attributed to "internal-engine", which owner-scoping treats as "all data". A token leak
  # then grants access to every owner's data. The fix — refuse an unattributed callback — is
  # not present yet → @pending probe on the intended owner-attribution helper.

  @pending
  Scenario: A callback with no owner attribution is refused
    Given the engine-to-workspace callback channel
    When the engine calls without an owner attribution header
    Then the callback is refused rather than treated as all-owner access
