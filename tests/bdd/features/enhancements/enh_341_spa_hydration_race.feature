# Issue #341 — adapters/browser/page_source.py:advance / _dom_changed (PlaywrightPageSource)
#   advance() end-detection checks URL change AND _dom_changed() right after clicking Next;
#   for SPAs with hash/query-only routing the new DOM may not have hydrated yet, so the
#   engine can skip a page or click both Save-and-Continue and Next on the same page.
# Requirement: advance()'s end-of-flow detection MUST re-check for a DOM change after a
#   short settle/retry when the URL did not change, so an un-hydrated SPA page is not
#   mistaken for the end of the flow.
# Related existing issue: #212 (_settle swallows the load-state timeout — same hydration risk).
# PENDING: a re-check/retry after the DOM-change probe (no such seam exists today).

Feature: SPA hydration does not cause advance() to skip or double-click a page

  Scenario: An un-hydrated SPA page is re-checked before declaring end of flow
    Given a page driver advancing through a single-URL SPA flow
    When advance detects no DOM change immediately after clicking Next
    Then it re-checks for the hydrated page before declaring the flow finished
