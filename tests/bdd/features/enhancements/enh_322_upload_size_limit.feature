Feature: Upload endpoints cap the request body to prevent disk/memory exhaustion
  # Issue #322 — fonts.py / onboarding.py (capped) + workspace/routes/gallery_routes.py (uncapped)
  # Requirement: Every file-upload endpoint MUST enforce a maximum body size and reject
  # an over-limit upload (HTTP 413) without buffering the whole payload in memory.

  Scenario: An over-limit font upload is rejected before it is fully buffered
    Given the font upload reader with a small byte cap
    When a body larger than the cap is streamed in
    Then the upload is rejected as too large

  Scenario: An over-limit base-resume upload is rejected
    Given the resume upload reader with a small byte cap
    When a body larger than the cap is streamed in
    Then the upload is rejected as too large

  Scenario: The gallery upload route enforces a body-size cap
    Given the gallery upload route module
    When it is inspected for an explicit upload size cap
    Then a maximum upload size is enforced on the gallery upload
