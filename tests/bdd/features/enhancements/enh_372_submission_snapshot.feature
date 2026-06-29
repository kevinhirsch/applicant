Feature: Every submission persists an immutable per-application snapshot
  # Issue #372 — prefill page-log ships (services/prefill_service.py PrefillResult);
  # a durable immutable submission snapshot is new. Pairs with the post-submission
  # lifecycle (#190-#193) and the document library (#289/#293).
  # Requirement: On submission (or review-approval at the stop-boundary), the engine
  # MUST persist an immutable snapshot per application — the exact field values/answers,
  # the material versions, the posting, and a timestamp — retrievable in the front-door.
  # GREEN: the pre-fill loop already records a per-page log of what was filled (transient).
  # PENDING: there is no durable, immutable, per-application submission snapshot.

  Scenario: The pre-fill loop records a per-page log of the values it filled
    Given a pre-fill result for an application
    When values are recorded for a page during pre-fill
    Then the per-page fill log carries the recorded values

  @pending
  Scenario: Submitting an application persists a snapshot of the exact answers and material versions
    Given an application about to be submitted with exact answers and material versions
    When the submission is recorded at the stop-boundary
    Then an immutable per-application snapshot of the answers, materials, posting, and timestamp is persisted

  @pending
  Scenario: The persisted snapshot is retrievable per application and immutable
    Given a persisted submission snapshot for an application
    When the snapshot is retrieved for that application
    Then it returns the exact submitted record and cannot be mutated after the fact
