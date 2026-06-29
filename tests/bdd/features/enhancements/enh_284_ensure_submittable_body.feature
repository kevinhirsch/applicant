# Issue #284 — ensure-submittable test only checks status 200 (app/routers/documents.py) — FR-RESUME-8
# GREEN: the endpoint confirms submittability in the BODY ({"submittable": true}); this
#        scenario asserts the body, not just the status code, and that the review gate
#        blocks (409) while material is unapproved.

Feature: ensure-submittable confirms submittability in the response body

  Scenario: The review gate blocks submission while generated material is unapproved
    Given the submission review gate over an unapproved generated material
    When submittability is checked
    Then the review gate refuses with a review-required error

  Scenario: An all-approved application is reported submittable in the body
    Given the submission review gate over only approved materials
    When submittability is checked
    Then the body confirms the application is submittable
