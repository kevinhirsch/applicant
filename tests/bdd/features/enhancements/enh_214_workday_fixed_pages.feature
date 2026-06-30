# Issue #214 — Workday model is exactly 6 fixed pages (adapters/browser/ats.py) — FR-PREFILL-2
# GREEN: regression confirming the CURRENT model — exactly 6 pages in fixed order.
# PENDING: real Workday tenants vary (10+ pages, no disclosures page, qualifications
#          pages, multi-part screening); the fake model exercises only the 6-page shape.

Feature: The Workday model handles tenant forms that vary from the fixed six pages

  Scenario: The shipped Workday model is exactly six pages in fixed order
    Given the Workday adapter
    When its modeled pages are listed
    Then there are exactly six pages with account-create first and final-submit last

  Scenario: A Workday tenant without a voluntary-disclosures page is supported
    Given a Workday tenant flow that omits the voluntary-disclosures page
    When the pre-fill loop walks the varied tenant flow
    Then the flow is handled without assuming the fixed six-page structure
